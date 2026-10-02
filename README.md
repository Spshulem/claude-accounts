# claude-accounts

Keep several Claude subscriptions logged in on one Mac and switch to the next
one automatically when the active one runs out of usage.

It works with the Claude Code CLI, [CCodex](https://github.com/gkorepanov/ccodex)
and [Conductor](https://conductor.build).

This is failover, not pooling. Claude Code stays on one account until that
account is nearly out of quota, then moves to the account with the most room
left. It does what running `/login` by hand would do, automatically.

> **Use at your own risk.** Only add accounts you own. Check that your use
> complies with [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms)
> and usage policies. Using several subscriptions to work past usage limits may
> not be allowed, and could get accounts restricted. The usage numbers come from
> an undocumented endpoint that can change or disappear at any time. This
> project is not affiliated with Anthropic.

## Requirements

- macOS (logins are read from the macOS Keychain)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH`
- `python3` (included with the Xcode Command Line Tools)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Spshulem/claude-accounts/main/install.sh | sh
```

Or from a clone:

```bash
git clone https://github.com/Spshulem/claude-accounts.git
cd claude-accounts
./claude-accounts install
```

`install` copies everything to `~/.claude-accounts/bin` and links
`claude-accounts` into `~/.local/bin`. It also starts the failover agent. If
CCodex is installed, it points CCodex's `claude_binary` at the wrapper. Use
`--no-agent` to skip the agent. The clone isn't needed afterwards.

## Set up accounts

Your current login in `~/.claude` is the `default` account. Add one slot for
each extra account:

```bash
claude-accounts add work           # create a slot
claude-accounts login work         # browser login, once per slot
claude-accounts status             # usage for every account
```

Use lowercase letters, digits, `-` or `_` in a label. Don't rename a slot
folder after logging it in: the Keychain item is named after its path, so the
renamed slot looks logged out.

## Use it with

### Claude Code CLI

Add this to your shell profile (`~/.zshrc`):

```bash
alias claude="$HOME/.claude-accounts/bin/claude"
```

Every new `claude` session starts on the active account. A session that is
already running keeps its account until you restart it.

### CCodex

`install` sets this up when `~/.ccodex` exists. If you install CCodex later,
run `claude-accounts install` again.

### Conductor

Conductor reads chat transcripts from `~/.claude` only, so it switches with a
long-lived token per slot instead of a different folder:

```bash
claude-accounts token work         # once per slot: browser login, saves a token to the Keychain
claude-accounts conductor on       # point Conductor at the wrapper
claude-accounts conductor off      # undo
```

`conductor on` tests the wrapper first, then sets `claude_code_executable_path`
in `~/.conductor/settings.toml` after backing up the file. New Conductor chats
use the active account. A slot without a token falls back to the `default`
login, so failover ranks token-less slots last while Conductor is connected.

## Day to day

```bash
claude-accounts status                       # * marks the active account
claude-accounts use work                     # switch; new sessions use it
claude-accounts use work --now               # also close CCodex/Conductor chats on other accounts
claude-accounts auto --dry-run               # what failover would do right now
claude-accounts auto --dry-run --threshold 40  # simulate a limit hit
tail ~/.claude-accounts/auto.log             # what failover did and why
```

## How it works

- Each extra account is a normal Claude Code config folder,
  `~/.claude-accounts/<label>/`, logged in with the official
  `claude auth login`. Each folder gets its own Keychain item, so every account
  stays signed in.
- Everything in `~/.claude` except the login is symlinked into each slot:
  settings, skills, agents, plugins and transcripts. A conversation can
  continue on another account. Only `.credentials.json` and `.claude.json`
  (the login and identity) are per slot.
- The wrapper `~/.claude-accounts/bin/claude` reads `~/.claude-accounts/ACTIVE`,
  sets `CLAUDE_CONFIG_DIR` and runs the real Claude Code. For CCodex it runs
  CCodex's own pinned copy, so CCodex's version check still passes.
- A LaunchAgent runs `claude-accounts auto` every 3 minutes, the usage
  endpoint's polling floor. It switches when the active account reaches **90%
  of its 5-hour session** or **97% of any weekly limit**, choosing the account
  with the most room. The session limit switches earlier because several
  percent can go between checks.
- Chats that are already running keep their account. Once an account is fully
  used up (a limit at 100%), `auto` closes the CCodex and Conductor Claude
  processes still on it, since every turn there fails anyway. The app resumes
  the chat from disk on the active account at the next message. Turns on an
  account that has only passed the switch point are left to finish. CLI
  sessions are never closed.

The tool only reads tokens. It never refreshes, copies or proxies them; Claude
Code refreshes each login itself when it is used.

A slot that only serves Conductor never uses its own login, so that login
expires after about 8 hours and its usage becomes unreadable. When that
happens, `auto` refreshes it the only way Claude Code allows: it sends one tiny
Haiku prompt through Claude Code on that slot, at most every 30 minutes. That
prompt saves nothing and loads no hooks or MCP servers. If a read still fails,
the last good reading is kept until its reset time, so an account known to be
used up is never picked.

## Uninstall

```bash
claude-accounts uninstall
```

This removes the agent and the wrappers, and switches CCodex and Conductor back
to their own Claude Code. Account slots stay in `~/.claude-accounts`. Delete
that folder to remove them, after running `claude auth logout` in each slot.

## License

MIT
