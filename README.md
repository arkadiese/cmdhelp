# cmdhelp

An interactive helper for shell commands. Start typing a command (`tar`, `awk`, `tcpdump`, `iptables`...) and it suggests options and ready-made combinations, each with an explanation. You pick one and the finished line lands in your shell prompt, ready to edit or run.

## Install

### Fedora / RHEL / Rocky / Alma / Oracle Linux / CentOS 7 (dnf or yum)

```sh
sudo curl -fsSL -o /etc/yum.repos.d/cmdhelp.repo https://arkadiese.github.io/cmdhelp/cmdhelp.repo
sudo dnf install cmdhelp
```

Or a single RPM without adding the repo:

```sh
sudo dnf install https://github.com/arkadiese/cmdhelp/releases/download/v0.2.0/cmdhelp-0.2.0-1.noarch.rpm
```

On EL7 (CentOS 7, RHEL 7, OL7), use `yum install cmdhelp`. Python 3.6 comes along from the base repo, and the package is
built to be readable by rpm 4.11. EL6 / OL6 ship no Python 3, so the RPM won't install there.

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
| `??` (no args) | Explains your previous command, what its exit code means, and what to try next |
| `cmdhelp --context` | Just the suggestions for where you are and what you last ran |
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

## Context: it knows what you just did

When you open the helper on an empty line, it starts from three things the shell already knows:
- **The last command and its exit code:**
  - after a failure: `[fix]` suggestions, picked by what failed and how (exit code)
  - after a success: `[next]` steps
- **The current directory:** `[here]` suggestions for the files in it.

| You just ran | Exit | It offers |
|---|---|---|
| `tar -xzf backup.tgz` | 2 | `file backup.tgz` (gzip, xz, or an HTML error page?), `tar -tvf backup.tgz \| head` |
| `curl https://api.example.com` | 7 | `nc -zv -w3 api.example.com 443`, `ip route get ...`, `curl -sSv ...` |
| `curl https://...` | 60 | `openssl s_client ... \| openssl x509 -noout -dates -issuer` |
| `systemctl restart nginx` | 1 | `systemctl status nginx -l --no-pager`, `journalctl -xeu nginx` |
| `ssh -p 2222 root@10.0.0.5` | 255 | `ssh -vvv -p 2222 ...`, `nc -zv 10.0.0.5 2222` |
| `grep a.b conf` | 1 | it says "no match is not an error", then `grep -i`, `grep -rn`, `grep -F` |
| `sl -la` | 127 | `ls -la` (only commands installed on this box) |
| `make` | 137 | "killed by SIGKILL, often the OOM killer", then `dmesg -T \| grep -i 'killed process'` |
| `sqlplus / as sysdba` | 1 | `echo $ORACLE_HOME $ORACLE_SID`, `lsnrctl status`, `ps -ef \| grep [p]mon_` |
| `vim /etc/ssh/sshd_config` | 0 | `sshd -t` (check before you restart and lock yourself out) |
| `firewall-cmd --add-port=8080/tcp` | 0 | `firewall-cmd --runtime-to-permanent` |
| `wget .../pkg.tar.gz` | 0 | `tar -tvf pkg.tar.gz`, `sha256sum`, `file` |

Ready-made use cases marked `*` have real file names from the current folder filled in:
`tar -xzvf archive.tar.gz` becomes `tar -xzvf backup-2026-11-25.tgz`.
Names the command would **write** (`tar -czf OUT`, `zip OUT`, `-o`, `-w`, `> file`) are never filled, so a suggestion can't overwrite an existing file.

**What it does not do:** it never reads command output or file contents, and it records nothing. It looks only at:
- names, sizes and dates in the current folder (at most 400 entries)
- the last command and its exit code

The shell passes these in environment variables of a short-lived subshell, never as arguments, so a password in your last command doesn't show up in `ps`.

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
the CLI, shell snippet syntax, and the opt-in gating of the profile.d hook. They also cover the context rules,
safe filling of file names, a guard that fails if the context code ever opens a file, and real bash/zsh sessions
on a terminal that confirm the widget passes exit code and last command via the environment, not argv.
CI (`.github/workflows/tests.yml`) runs them on every push to `main`, on CentOS 7 (Python 3.6, bash 4.2), Rocky 8, Rocky 9,
Fedora and Python 3.12. It also builds the RPM on Fedora and installs that exact file with yum/dnf on CentOS 7, Rocky 8,
Rocky 9 and Fedora.

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
