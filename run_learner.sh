#!/bin/bash
# Gold Trading Bot — Dual-Source Learner Service (auto-restart)
# Runs TWO learning processes with automatic restart on failure:
#   1. TradingView multi-TF snapshots (5M/15M/1H/4H/1D every 5 min)
#   2. OANDA real-time tick stream (every price change, auto-reconnect)

export PATH="/opt/anaconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Portable configuration (the original hardcoded one machine's home folder).
# Each value can be overridden with an environment variable; the defaults reproduce
# the original behaviour when this script sits in the project folder.
#   GOLD_BOT_DIR  project folder      (default: the folder containing this script)
#   PYTHON        Python interpreter  (default: /opt/anaconda3/bin/python if present, else python3)
#   LOGDIR        log folder          (default: $GOLD_BOT_DIR/logs)
export HOME="${HOME:-$(cd ~ && pwd)}"
GOLD_BOT_DIR="${GOLD_BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
if [ -z "${PYTHON:-}" ]; then
    if [ -x /opt/anaconda3/bin/python ]; then PYTHON=/opt/anaconda3/bin/python; else PYTHON=python3; fi
fi
cd "$GOLD_BOT_DIR" || exit 1

LOGDIR="${LOGDIR:-$GOLD_BOT_DIR/logs}"
mkdir -p "$LOGDIR"

# Function: run a process in a restart loop
run_forever() {
    local NAME=$1
    shift
    while true; do
        echo "$(date): [$NAME] Starting..." >> "$LOGDIR/service.log"
        "$@" >> "$LOGDIR/learner_${NAME}.log" 2>&1
        EXIT_CODE=$?
        echo "$(date): [$NAME] Exited with code $EXIT_CODE, restarting in 15s..." >> "$LOGDIR/service.log"
        sleep 15
    done
}

# Start both in background with auto-restart
run_forever "tradingview" "$PYTHON" main.py learn-deep --interval 300 &
TV_PID=$!

run_forever "oanda" "$PYTHON" main.py learn-live &
OANDA_PID=$!

echo "$(date): Service started — TV PID=$TV_PID, OANDA PID=$OANDA_PID" >> "$LOGDIR/service.log"

# Trap to clean up on service stop
cleanup() {
    echo "$(date): Service stopping..." >> "$LOGDIR/service.log"
    kill $TV_PID $OANDA_PID 2>/dev/null
    wait $TV_PID $OANDA_PID 2>/dev/null
    echo "$(date): Service stopped." >> "$LOGDIR/service.log"
    exit 0
}
trap cleanup SIGTERM SIGINT

# Keep alive with caffeinate (prevents sleep)
/usr/bin/caffeinate -s -w $$ &

# Wait forever
wait
