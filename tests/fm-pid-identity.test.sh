#!/usr/bin/env bash
# tests/fm-pid-identity.test.sh - fm_pid_identity must produce a STABLE
# process-identity token for an unchanged pid. The old impl built it from
# `ps -o lstart`, an absolute wall-clock start time (boot_epoch + starttime);
# on WSL2 the boot epoch drifts against the wall clock, so that string drifts
# forward for one unchanged pid and the watch-arm identity gate false-rejects a
# healthy watcher as FAILED. The fix reads /proc/<pid>/stat field 22 (starttime
# in jiffies since boot), which is monotonic and boot-relative. These units pin
# both the stability property and the comm-with-spaces/parens parse.
set -u

# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

LIB="$ROOT/bin/fm-wake-lib.sh"
# shellcheck disable=SC1090
. "$LIB"

test_identity_is_stable_across_real_time() {
  # A live pid's identity, read twice with real time between the reads, must be
  # the exact same string. This fails on the old ps-lstart impl under WSL2 (the
  # value drifts) and passes everywhere on the /proc-starttime impl.
  local first second
  first=$(fm_pid_identity "$$") || fail "fm_pid_identity returned non-zero for a live pid"
  [ -n "$first" ] || fail "fm_pid_identity produced an empty identity for a live pid"
  sleep 2
  second=$(fm_pid_identity "$$") || fail "fm_pid_identity returned non-zero on the second read"
  [ "$first" = "$second" ] || fail "identity drifted across real time: '$first' != '$second'"
  pass "fm_pid_identity is stable for an unchanged pid across real time"
}

test_proc_stat_parse_handles_comm_with_spaces_and_parens() {
  # Field 2 (comm) can contain spaces and parentheses; the parser must strip
  # through the LAST ') ' before indexing, so field 22 (starttime) is extracted
  # from the real columns, not from inside the comm.
  local line start
  # comm = "(my (weird) proc)"; remaining fields are state(3) ... starttime(22).
  # Columns 3..22:  S 1 1234 1234 0 -1 4194560 100 0 0 0 5 6 0 0 20 0 1 0 727865
  line='1234 (my (weird) proc) S 1 1234 1234 0 -1 4194560 100 0 0 0 5 6 0 0 20 0 1 0 727865'
  start=$(fm_proc_stat_starttime "$line") || fail "parser returned non-zero for a valid stat line"
  [ "$start" = "727865" ] || fail "starttime parsed wrong: expected 727865, got '$start'"
  pass "proc-stat parser extracts starttime past a comm with spaces and parens"
}

test_proc_stat_parse_handles_plain_comm() {
  # A boring single-word comm must parse identically.
  local line start
  line='42 (bash) S 1 42 42 0 -1 4194304 50 0 0 0 1 2 0 0 20 0 1 0 555000'
  start=$(fm_proc_stat_starttime "$line") || fail "parser returned non-zero for a plain stat line"
  [ "$start" = "555000" ] || fail "starttime parsed wrong for plain comm: expected 555000, got '$start'"
  pass "proc-stat parser extracts starttime for a plain comm"
}

test_pid_identity_rejects_bad_pids() {
  # Empty and non-numeric pids are rejected; a dead pid produces no identity.
  fm_pid_identity "" && fail "empty pid was not rejected"
  fm_pid_identity "abc" && fail "non-numeric pid was not rejected"
  local dead
  dead=999999
  while kill -0 "$dead" 2>/dev/null; do dead=$((dead + 1)); done
  fm_pid_identity "$dead" && fail "dead pid produced an identity"
  pass "fm_pid_identity rejects empty, non-numeric, and dead pids"
}

test_identity_is_stable_across_real_time
test_proc_stat_parse_handles_comm_with_spaces_and_parens
test_proc_stat_parse_handles_plain_comm
test_pid_identity_rejects_bad_pids
