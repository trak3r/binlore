#!/usr/bin/env bash
set -u
cd /Users/ted/personal/binlore
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
LOG=tools/runs/crum-punch-extract.log
: > "$LOG"
ok=0; fail=0
extract_one() {
  local id="$1"
  echo "" | tee -a "$LOG"
  echo "========== $(date -u +%Y-%m-%dT%H:%M:%SZ) START $id ==========" | tee -a "$LOG"
  if ./binlore extract "$id" >>"$LOG" 2>&1; then
    ./binlore update-wiki "$id" >>"$LOG" 2>&1 || true
    echo "OK $id" | tee -a "$LOG"
    ok=$((ok+1))
  else
    echo "FAIL $id" | tee -a "$LOG"
    fail=$((fail+1))
  fi
  sleep 5
}
for id in QRN1ZIHDHG8 gnN-yI8Xmdw b9tvtwX2zQA 3hRyg_SPR8o S_KvZRUJpIw 4x739N7tVeE; do
  extract_one "$id"
done
echo "" | tee -a "$LOG"
echo "========== $(date -u +%Y-%m-%dT%H:%M:%SZ) START -DKnhDrOWFQ ==========" | tee -a "$LOG"
if ./binlore extract -- -DKnhDrOWFQ >>"$LOG" 2>&1; then
  ./binlore update-wiki -- -DKnhDrOWFQ >>"$LOG" 2>&1 || true
  echo "OK -DKnhDrOWFQ" | tee -a "$LOG"; ok=$((ok+1))
else
  echo "FAIL -DKnhDrOWFQ" | tee -a "$LOG"; fail=$((fail+1))
fi
sleep 5
for id in BQ8yOTL7uU8 _nvoKaHtAIU ERveBURDEZ4 03maVjRy6EE X-zigNPGBUA lZ9b1vOwa9w m-flygfm2xU QDY1wkyfA-k; do
  extract_one "$id"
done
echo "" | tee -a "$LOG"
echo "========== $(date -u +%Y-%m-%dT%H:%M:%SZ) DONE ok=$ok fail=$fail (kmm6ANnhWcQ done earlier) ==========" | tee -a "$LOG"
echo "Done. Log: $LOG"
