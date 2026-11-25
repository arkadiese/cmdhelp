# cmdhelp

An interactive helper for shell commands. Start typing a command (`tar`, `awk`, `tcpdump`, `iptables`...) and it suggests options and ready-made combinations, each with an explanation. You pick one and the finished line lands in your shell prompt, ready to edit or run.

## Install

### Fedora / RHEL / Rocky / Alma (dnf)

```sh
sudo curl -fsSL -o /etc/yum.repos.d/cmdhelp.repo https://arkadiese.github.io/cmdhelp/cmdhelp.repo
sudo dnf install cmdhelp
```

Or a single RPM without adding the repo:

```sh
sudo dnf install https://github.com/arkadiese/cmdhelp/releases/download/v0.1.0/cmdhelp-0.1.0-1.noarch.rpm
```

The package installs `/usr/bin/cmdhelp` and changes nobody's shell until they opt in:

```sh
cmdhelp --enable        # for your user: keybindings + ?? in new bash shells (cmdhelp --disable to undo)
```

- For zsh, also add `source /usr/share/cmdhelp/cmdhelp.zsh` to `~/.zshrc`.
- An admin can enable it for every user with `sudo touch /etc/cmdhelp/enable-all`.
- `CMDHELP_DISABLE=1` always wins.

### Anywhere else

```sh
sh install.sh            # copies cmdhelp.pyz to ~/.local/bin, adds a line to ~/.bashrc and ~/.zshrc
```

Requirements: Python 3.6 or newer, nothing else (prompt_toolkit is bundled inside the .pyz).
For a server where you don't want to install anything, copy only `cmdhelp.pyz` (attached to every GitHub release) and run `python3 cmdhelp.pyz`.

## Use

| Key / command | What it does |
|---|---|
| **Ctrl+Space**, **Alt+h** (or **Esc** then **h**), **Ctrl+X** then **h** in bash/zsh | Opens the helper with whatever you already typed. Ctrl+X h works in terminals that swallow the others (MobaXterm, PuTTY). |
| `cmdhelp` | Opens the helper standalone (prints the chosen line) |
| `?? <command line>` | Explains a command line token by token |
| `??` (no args) | Explains your previous command |
| `cmdhelp -s tar` | Cheat sheet for a command |
| `cmdhelp -m verbose ...` | Picks a mode (`min`, `normal`, `verbose`; or set `CMDHELP_MODE`) |

Inside the helper:

- **Type a command name** to get suggestions ranked by your own shell history first, then by the top-500 list.
- **Type a word that isn't a command** (`compress`, `firewall`, `dns`) to see commands that do that.
- **`-`** lists options with explanations. Keep typing letters to build bundles: `tar -xz` suggests `v` and `f` next, learned from real use cases.
- **Space, then keywords** filters ready-made combos: `tar exclude`, `find delete`, `tcpdump syn`, `rsync mirror`, `ssh tunnel`.
- **Enter** on a combo puts the whole line in your prompt. Enter on an option inserts it and you keep typing. Enter with nothing highlighted accepts the line.
- **F2** cycles the mode (minimal, normal, verbose). **F3** shows the cheat sheet. **F1** shows help. **PgUp/PgDn** scroll. **Esc** quits.

Nothing is ever executed. The helper only edits your prompt line.

## Modes

- **minimal**: a few words per token, e.g. `-c (create) -z (gzip) -v (verbose) -f (archive file)`
- **normal**: one clear sentence per token
- **verbose**: the full explanation with why and when, examples, the common traps people hit on StackOverflow and ServerFault, related combos, and "see also"

## Where the knowledge comes from

| Source | Coverage |
|---|---|
| Hand-curated entries | 41 core tools in depth: dnf, tar, gzip, gunzip, zip, unzip, xz, grep, awk, sed, find, xargs, sort, uniq, cut, cat, head, tail, wc, tr, tcpdump, iptables, ss, ip, curl, ssh, rsync, nc, nmap, dig, ls, ps, kill, systemctl, journalctl, chmod, chown, du, df, lsof, openssl. Every flag has 3 text levels, plus use cases and pitfalls drawn from the most-voted StackOverflow/unix.SE/ServerFault questions. |
| tldr-pages (GitHub, CC-BY 4.0) | 6,830 commands with community-written use cases (common + linux pages) |
| Your local man pages | Parsed in a background thread the first time you use a command, so typing never waits on `man`. Cached in `~/.cache/cmdhelp`, and re-parsed when the man page changes (path + mtime) or the parser version changes. Best-effort: curated and tldr text always wins. |
| Ranking | A list of 544 commands in 60+ categories (`build/top500.txt`), re-ranked live by your `~/.bash_history` / `~/.zsh_history` |

## Rebuild / extend

```sh
git clone --depth 1 https://github.com/tldr-pages/tldr.git ../tldr
python3 build/build_kb.py ../tldr cmdhelp/data/kb.json.gz
python3 build/make_pyz.py          # writes dist/cmdhelp.pyz
sh packaging/build_rpm.sh          # writes dist/cmdhelp-<ver>-1.noarch.rpm (needs rpm-build)
```

### Tests

```sh
python3 -m unittest discover -s tests -t .
```

The tests use stdlib `unittest` only, so they run unchanged on Python 3.6. They cover the tokenizer, the explainer
(bundles, `ps aux`, `find -exec`, `sudo`, pipelines, redirects), ranking and history parsing, the man parser
(GNU/BSD layouts, malformed input), cache invalidation and atomic writes, background enrichment, the completer,
the CLI, shell snippet syntax, and the opt-in gating of the profile.d hook.
CI (`.github/workflows/tests.yml`) runs them on every push to `main`, on Rocky 8 (Python 3.6), Rocky 9, Fedora, and Python 3.12.

### Supported shell syntax

The explainer understands:
- simple commands, `VAR=x` and wrapper prefixes (`sudo`, `time`, `nohup`, `env`, `timeout`...)
- pipes and `&&` `||` `;` `&`
- redirections (`>`, `>>`, `<`, `2>`, `2>&1`, `&>`, here-string `<<<`)
- quoted arguments, `--`, short-option bundles, BSD letter style (`ps aux`, `tar xzf`), and `find -exec ... \;` / `+`

Process substitution `<( )`, subshells `( )`, `$( )`, and multi-line heredocs are not parsed. They don't crash; the affected tokens are shown as plain arguments.

### Releasing

Bump `__version__` in `cmdhelp/__init__.py`, push, then publish a GitHub Release tagged `vX.Y.Z`
(Releases > Draft a new release, or `gh release create vX.Y.Z --generate-notes`).
The GitHub Actions workflow then does the following:
1. Builds and smoke-tests the RPM in a Fedora container.
2. Attaches the RPM and the .pyz to a GitHub Release.
3. Republishes the dnf repo on GitHub Pages.

To add or deepen a command, add a `cmd(...)` block in `build/curated/*.py`. The DSL is in `_dsl.py`: `F()` defines a flag and `C()` a combo, each taking `min` / `normal` / `verbose` text. Then rebuild.

## Layout

```
cmdhelp/            runtime package (stdlib only + vendored prompt_toolkit 3.0.36)
  kb.py             KB loading, history ranking, man-page option parser
  explain.py        tokenizer + explainer (pipes, redirects, sudo, bundles like -xzvf / ps aux, subcommands)
  tui.py            prompt_toolkit interface
  data/kb.json.gz   built knowledge base (1.1 MB)
build/              knowledge-base sources and build scripts
packaging/          RPM spec, profile.d hook, bash/zsh snippets, build_rpm.sh
.github/workflows/  release pipeline (RPM + GitHub Release + dnf repo on Pages)
install.sh
```

## License

MIT for cmdhelp itself. Bundled third-party material:
- tldr-pages content (in `cmdhelp/data/kb.json.gz`), CC-BY 4.0, https://github.com/tldr-pages/tldr
- prompt_toolkit 3.0.36 (BSD-3-Clause) and wcwidth 0.2.13 (MIT), in `cmdhelp/_vendor/`
