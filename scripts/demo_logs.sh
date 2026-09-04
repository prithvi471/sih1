#!/usr/bin/env bash
# MineIQ live agent feed for demos.
# Streams every service's logs into one terminal, relabels each with a friendly
# AGENT tag + colour, and filters out health-checks and internal chatter so the
# judge sees only meaningful pipeline activity as you click in the frontend.
#
# Usage (from the mineiq/ directory):
#   bash scripts/demo_logs.sh
#
# Press Ctrl+C to stop. Focus a single agent instead with, e.g.:
#   docker compose logs -f rag-service
cd "$(dirname "$0")/.." || exit 1

SERVICES="ingestion-service ocr-service validation-service classification-service rag-service analytics-service report-generation-worker triage-worker topic-modeling-worker"

# Lines we never want to see during a demo.
NOISE='/health|OPTIONS |HEAD /|GET / HTTP|pika\.|Socket|transport|Streaming|AMQPConn|channel=|reporting success|connecting to|linked up|blocking_conn|User-initiated|Deactivat|Aborting|_initate|Created channel|Closing conn|Stack term|AMQP stack|Uvicorn running|Started server process|Application startup|Waiting for application|Watchfiles|watchfiles|Reloading|Started reloader'

docker compose logs -f --tail=0 $SERVICES 2>/dev/null \
  | grep --line-buffered -viE "$NOISE" \
  | awk '
    BEGIN {
      map["ingestion-service"]="ORCHESTRATOR"; col["ingestion-service"]="\033[1;36m";
      map["ocr-service"]="OCR / EXTRACT";      col["ocr-service"]="\033[1;33m";
      map["validation-service"]="VALIDATION";  col["validation-service"]="\033[1;35m";
      map["classification-service"]="CLASSIFY (LLM)"; col["classification-service"]="\033[1;34m";
      map["rag-service"]="RAG / ASK-AI";       col["rag-service"]="\033[1;32m";
      map["analytics-service"]="ANALYTICS";    col["analytics-service"]="\033[1;36m";
      map["report-generation-worker"]="REPORT WORKER"; col["report-generation-worker"]="\033[1;92m";
      map["triage-worker"]="TRIAGE";           col["triage-worker"]="\033[1;91m";
      map["topic-modeling-worker"]="TOPIC MODEL"; col["topic-modeling-worker"]="\033[1;95m";
      reset="\033[0m";
    }
    {
      p=index($0,"|");
      svc=substr($0,1,p-1); gsub(/[ \t]+$/,"",svc); gsub(/^[ \t]+/,"",svc);
      sub(/^mineiq-/,"",svc);   # container_name prefix -> service name
      line=substr($0,p+1);
      label=(svc in map)?map[svc]:svc;
      c=(svc in col)?col[svc]:"\033[1;37m";
      printf "%s%-16s%s |%s\n", c, "["label"]", reset, line;
      fflush();
    }'
