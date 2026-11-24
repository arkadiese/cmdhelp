"""Interactive TUI: type a command, get live suggestions + explanations."""
import os
import re
import sys

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import has_completions, completion_is_selected
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window, FloatContainer, Float
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style

from .kb import MODES, PREFIX_CMDS
from .explain import tokenize, render_text, render_command, explain

MODE_LABEL = {"min": "MINIMAL", "normal": "NORMAL", "verbose": "VERBOSE"}


class State(object):
    def __init__(self, mode):
        self.mode = mode
        self.view = "explain"     # explain | sheet | help
        self.scroll = 0


def _real_cmd(words):
    i = 0
    while i < len(words) and (words[i] in PREFIX_CMDS or re.match(r"^[A-Za-z_]\w*=", words[i]) or (i > 0 and words[i].startswith("-") and words[0] in PREFIX_CMDS)):
        i += 1
    return (words[i], i) if i < len(words) else (None, i)


class HelperCompleter(Completer):
    def __init__(self, kb, state):
        self.kb = kb
        self.state = state
        self.paths = PathCompleter(expanduser=True)

    def _meta(self, text):
        text = text or ""
        lim = 45 if self.state.mode == "min" else 90
        return text if len(text) <= lim else text[:lim - 1] + "~"

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # only look at the current pipeline segment
        seg_start = max(text.rfind("|"), text.rfind("&&"), text.rfind(";"))
        seg_text = text[seg_start + 1:] if seg_start >= 0 else text
        if seg_start >= 0 and text[seg_start:seg_start + 2] == "&&":
            seg_text = text[seg_start + 2:]
        lead = len(seg_text) - len(seg_text.lstrip())
        seg_text = seg_text.lstrip()
        words = seg_text.split()
        cur = "" if (not seg_text or seg_text.endswith(" ")) else words[-1]
        done = words if cur == "" else words[:-1]
        cmd, cmd_i = _real_cmd(done)
        mode = self.state.mode

        # ---- typing the command name ----
        if cmd is None:
            seen = set()
            names = self.kb.ranked_names(cur)[:60]
            for n in names:
                seen.add(n)
                yield Completion(n, start_position=-len(cur), display=n,
                                 display_meta=self._meta(self.kb.summary(n, "min" if mode == "min" else "normal")))
            # intent search: "compress", "firewall", "dns" ...
            if len(cur) >= 3 and len(names) < 8:
                hits = []
                lc = cur.lower()
                for n in self.kb.rank:
                    s = self.kb.summary(n, "normal").lower()
                    if n not in seen and lc in s:
                        hits.append(n)
                for n in hits[:25]:
                    yield Completion(n, start_position=-len(cur), display="%s" % n,
                                     display_meta=self._meta("[match] " + self.kb.summary(n, "normal")))
            return

        entry = self.kb.get(cmd)
        sub_entry_name = None
        positional = [w for w in done[cmd_i + 1:] if not w.startswith("-")]
        if entry and positional and self.kb.has(cmd + "-" + positional[0]):
            sub_entry_name = cmd + "-" + positional[0]
        e = self.kb.get(sub_entry_name) if sub_entry_name else entry
        if not e:
            for c in self.paths.get_completions(Document(cur, len(cur)), complete_event):
                yield c
            return

        # ---- flags ----
        if cur.startswith("-"):
            used = set(done)
            emitted = set()
            for f in e["flags"]:
                for n in f["names"]:
                    if n.startswith(cur) and n not in emitted:
                        emitted.add(n)
                        disp = n + ((" " + f["arg"]) if f.get("arg") else "")
                        yield Completion(n + (" " if f.get("arg") else ""), start_position=-len(cur), display=disp,
                                         display_meta=self._meta(f.get(mode if mode != "verbose" else "normal")),
                                         style="class:used" if n in used else "")
                        break
            # bundle building: -xz -> -xzv, -xzf ...
            if re.match(r"^-[a-zA-Z]+$", cur) and len(cur) >= 2:
                have = set(cur[1:])
                # learn likely next letters from the use-case corpus
                weight = {}
                for c in e.get("combos", []):
                    for tok in c["cmd"].split():
                        if tok.startswith("-") and not tok.startswith("--") and set(cur[1:]) <= set(tok[1:]):
                            for ch in tok[1:]:
                                if ch not in have:
                                    weight[ch] = weight.get(ch, 0) + 1
                cands = []
                for f in e["flags"]:
                    for n in f["names"]:
                        if re.match(r"^-[a-zA-Z]$", n) and n[1] not in have:
                            cands.append((-weight.get(n[1], 0), n[1], f))
                            break
                cands.sort(key=lambda x: x[0])
                for w, ch, f in cands:
                    yield Completion(cur + ch, start_position=-len(cur), display=cur + ch,
                                     display_meta=self._meta(("* " if w else "+ ") + f.get(mode if mode != "verbose" else "normal", "")))
            return

        # ---- subcommands (first positional) ----
        subs = e.get("subcommands") or {}
        if not positional and subs and not sub_entry_name:
            for s, d in sorted(subs.items(), key=lambda kv: (not kv[0].startswith(cur), kv[0])):
                if s.startswith(cur):
                    yield Completion(s, start_position=-len(cur), display=s, display_meta=self._meta(d), style="class:sub")

        # ---- ready-made combos: filter by keywords typed after the command ----
        keywords = [w.lower() for w in (positional + ([cur] if cur else [])) if not w.startswith("-")]
        flags_typed = [w for w in done[cmd_i + 1:] if w.startswith("-")]
        line_start = len(text) - len(seg_text) - lead
        count = 0
        for c in e.get("combos", []):
            hay = (c["cmd"] + " " + c["normal"] + " " + " ".join(c.get("tags", []))).lower()
            if keywords and not all(k in hay for k in keywords):
                continue
            if flags_typed and not all(f in c["cmd"] or all(ch in c["cmd"] for ch in f[1:]) for f in flags_typed):
                continue
            count += 1
            yield Completion(c["cmd"], start_position=-(len(text) - line_start - lead) - lead,
                             display=c["cmd"], display_meta=self._meta(c["min"] if mode == "min" else c["normal"]),
                             style="class:combo")
            if count >= 40:
                break
        # ---- paths ----
        if cur and ("/" in cur or cur.startswith(".") or cur.startswith("~")):
            for c in self.paths.get_completions(Document(cur, len(cur)), complete_event):
                yield c


HELP = """<b>cmdhelp</b>  interactive shell command helper

  Type a command name: ranked suggestions (your shell history first, then the top-500 list).
  Type a word that is not a command (e.g. <i>compress</i>, <i>firewall</i>): matching commands.
  After the command:
     <b>-</b>           options with explanations; keep typing letters to build bundles like -xzvf
     <b>space</b>       ready-made combinations (use cases), subcommands
     <b>words</b>       filter combinations: <i>tar exclude</i>, <i>find delete old</i>, <i>tcpdump syn</i>

  <b>Tab / arrows</b>  pick a suggestion          <b>Enter</b>  accept line (or apply highlighted suggestion)
  <b>F2</b>  cycle mode: minimal / normal / verbose
  <b>F3</b>  cheat sheet of the current command      <b>F1</b>  this help
  <b>PgUp/PgDn</b>  scroll the lower pane            <b>Ctrl-C / Esc</b>  quit without output
"""


def run_tui(kb, mode="normal", initial="", result_file=None):
    state = State(mode)
    completer = HelperCompleter(kb, state)
    buf = Buffer(completer=completer, complete_while_typing=True, multiline=False,
                 document=Document(initial, len(initial)))

    def current_target_line():
        # prompt_toolkit already writes the highlighted completion into the buffer
        cs = buf.complete_state
        return buf.text.strip(), bool(cs and cs.current_completion)

    def lower_text():
        if state.view == "help":
            return HTML(HELP)
        line, preview = current_target_line()
        if not line:
            top = [n for n, _ in kb.history.most_common(12) if kb.has(n)] or kb.rank[:12]
            return ANSI("\033[2mStart typing a command (F1 for help). Your most used: \033[0m\033[1;36m" + "  ".join(top) + "\033[0m")
        if state.view == "sheet":
            words = line.split()
            cmd, _ = _real_cmd(words)
            if cmd and len(words) > 1 and kb.has(cmd + "-" + words[words.index(cmd) + 1] if words.index(cmd) + 1 < len(words) else ""):
                cmd = cmd + "-" + words[words.index(cmd) + 1]
            txt = render_command(kb, cmd, state.mode) if cmd else ""
        else:
            head = ("\033[2mpreview of highlighted suggestion:\033[0m\n" if preview else "")
            txt = head + "\033[1m$ " + line + "\033[0m\n\n" + render_text(kb, line, state.mode)
        lines = txt.split("\n")
        state.scroll = max(0, min(state.scroll, len(lines) - 1))
        return ANSI("\n".join(lines[state.scroll:]))

    def toolbar():
        return HTML(" <b>[%s]</b>  F1 help  F2 mode  F3 %s  Tab complete  Enter accept  Esc quit  "
                    % (MODE_LABEL[state.mode], "explain" if state.view == "sheet" else "cheat sheet"))

    kbind = KeyBindings()

    @kbind.add("f2")
    @kbind.add("c-t")
    def _(event):
        state.mode = MODES[(MODES.index(state.mode) + 1) % 3]
        state.scroll = 0
        if buf.complete_state:
            buf.start_completion(select_first=False)

    @kbind.add("f3")
    def _(event):
        state.view = "explain" if state.view == "sheet" else "sheet"
        state.scroll = 0

    @kbind.add("f1")
    def _(event):
        state.view = "explain" if state.view == "help" else "help"

    @kbind.add("pagedown")
    def _(event):
        state.scroll += 10

    @kbind.add("pageup")
    def _(event):
        state.scroll = max(0, state.scroll - 10)

    @kbind.add("enter")
    def _(event):
        cs = buf.complete_state
        if cs and cs.current_completion:
            c = cs.current_completion
            is_combo = "combo" in (c.style or "")
            buf.apply_completion(c)
            if is_combo:   # a whole ready-made line: hand it to the shell prompt
                event.app.exit(result=buf.text.strip())
                return
            if not c.text.endswith(" ") and not c.text.endswith("/"):
                buf.insert_text(" ")
            return
        event.app.exit(result=buf.text.strip())

    @kbind.add("c-c")
    @kbind.add("escape", eager=True)
    def _(event):
        if buf.complete_state:
            buf.cancel_completion()
        else:
            event.app.exit(result=None)

    @kbind.add("c-d")
    def _(event):
        event.app.exit(result=None)

    input_win = Window(BufferControl(buffer=buf), height=1, get_line_prefix=lambda *a: [("class:prompt", "$ ")])
    lower = Window(FormattedTextControl(lower_text), wrap_lines=True, height=Dimension(min=6, preferred=20))
    body = FloatContainer(
        content=HSplit([
            input_win,
            Window(height=1, char="-", style="class:line"),
            lower,
            Window(FormattedTextControl(toolbar), height=1, style="class:toolbar"),
        ]),
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=14, scroll_offset=1))],
    )
    style = Style.from_dict({
        "prompt": "bold ansigreen", "line": "ansibrightblack", "toolbar": "reverse",
        "completion-menu.completion": "bg:#262626 #d0d0d0",
        "completion-menu.completion.current": "bg:#005f87 #ffffff bold",
        "completion-menu.meta.completion": "bg:#1c1c1c #8a8a8a",
        "completion-menu.meta.completion.current": "bg:#005f87 #ffffff",
        "combo": "#87d7ff", "sub": "#d7af5f", "used": "#6c6c6c",
    })

    io_kwargs = {}
    tty_in = tty_out = None
    if result_file or not sys.stdout.isatty():
        try:
            from prompt_toolkit.input import create_input
            from prompt_toolkit.output import create_output
            tty_in = open("/dev/tty", "r")
            tty_out = open("/dev/tty", "w")
            io_kwargs = {"input": create_input(stdin=tty_in), "output": create_output(stdout=tty_out)}
        except (IOError, OSError):
            pass

    app = Application(layout=Layout(body, focused_element=input_win), key_bindings=kbind, style=style,
                      full_screen=False, mouse_support=False, erase_when_done=True, **io_kwargs)
    if initial:
        buf.start_completion(select_first=False)
    result = app.run()
    for f in (tty_in, tty_out):
        if f:
            f.close()
    if result:
        if result_file:
            with open(result_file, "w") as fh:
                fh.write(result)
        else:
            print(result)
    return result
