%{!?pkg_version: %global pkg_version 0.2.0}

Name:           cmdhelp
Version:        %{pkg_version}
Release:        1%{?dist}
Summary:        Interactive shell command helper with explained options and ready-made use cases
License:        MIT AND CC-BY-4.0 AND BSD-3-Clause
URL:            https://github.com/arkadiese/cmdhelp
Source0:        cmdhelp.pyz
Source1:        cmdhelp.sh
Source2:        cmdhelp.bash
Source3:        cmdhelp.zsh
BuildArch:      noarch

Requires:       /usr/bin/python3
Recommends:     man-db
Provides:       bundled(python3-prompt-toolkit) = 3.0.36
Provides:       bundled(python3-wcwidth) = 0.2.13

%description
Start typing a command (tar, awk, grep, tcpdump, iptables...) and cmdhelp
suggests options and ready-made combinations, each with an explanation in
minimal, normal or verbose mode. The chosen line is placed in your prompt,
never executed. Shell keybindings are opt-in per user (cmdhelp --enable):
Ctrl+Space, Alt+h or Ctrl+X h open it from bash or zsh, and ?? explains the
previous command. Knowledge: 40 hand-curated core tools, 6,830 tldr-pages
commands, and local man pages parsed on demand.

%prep

%build

%install
install -Dpm 0644 %{SOURCE0} %{buildroot}%{_datadir}/cmdhelp/cmdhelp.pyz
install -Dpm 0644 %{SOURCE2} %{buildroot}%{_datadir}/cmdhelp/cmdhelp.bash
install -Dpm 0644 %{SOURCE3} %{buildroot}%{_datadir}/cmdhelp/cmdhelp.zsh
install -Dpm 0644 %{SOURCE1} %{buildroot}%{_sysconfdir}/profile.d/cmdhelp.sh
install -d %{buildroot}%{_sysconfdir}/cmdhelp
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/cmdhelp <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/share/cmdhelp/cmdhelp.pyz "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/cmdhelp

%files
%{_bindir}/cmdhelp
%dir %{_datadir}/cmdhelp
%{_datadir}/cmdhelp/cmdhelp.pyz
%{_datadir}/cmdhelp/cmdhelp.bash
%{_datadir}/cmdhelp/cmdhelp.zsh
%config(noreplace) %{_sysconfdir}/profile.d/cmdhelp.sh
%dir %{_sysconfdir}/cmdhelp

%changelog
* Wed Nov 25 2026 Arkasha <arkadiese@users.noreply.github.com> - 0.2.0-1
- Keybindings are now opt-in per user (cmdhelp --enable) or via /etc/cmdhelp/enable-all
- Ctrl+X h fallback key for terminals that swallow Ctrl+Space/Alt (MobaXterm, PuTTY)
- man-page parsing moved off the typing path; cache invalidated by man page mtime and parser version
- Unit test suite, CI on Python 3.6 (Rocky 8) through current Fedora

* Tue Nov 24 2026 Arkasha <arkadiese@users.noreply.github.com> - 0.1.0-1
- Initial package
