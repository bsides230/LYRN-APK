#!/usr/bin/env bash
# lcc - Local Claude Code launcher for LYRN
# Points Claude Code at the LYRN Anthropic Proxy
#
# Usage:
# lcc <modelname> — launch Claude Code with the specified model
# lcc <modelname> [args] — pass additional arguments to claude
# lcc — show help/launch with model if one is available

LCC_HOST="${LCC_HOST:-127.0.0.1}"

# Attempt to read port from port.txt + 1
DEFAULT_PORT=8001
if [ -f "port.txt" ]; then
  PORT_VAL=$(cat port.txt)
  if [[ "$PORT_VAL" =~ ^[0-9]+$ ]]; then
    DEFAULT_PORT=$((PORT_VAL + 1))
  fi
fi

LCC_PORT="${LCC_PORT:-$DEFAULT_PORT}"
LCC_BASE_URL="http://${LCC_HOST}:${LCC_PORT}"

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'
BOLD='\033[1m'

# No model argument, show help and check server
if [[ -z "$1" ]]; then
  echo -e "${BOLD}Local Claude Code${NC} (${CYAN}LYRN @ ${LCC_HOST}:${LCC_PORT}${NC})"
  echo ""

  # Check if server is reachable
  if curl -sf "${LCC_BASE_URL}/health" > /dev/null 2>&1; then
    echo -e "${GREEN} LYRN Anthropic Proxy is running${NC}"

    # Try to get the loaded model name from /v1/models
    MODEL_INFO=$(curl -sf "${LCC_BASE_URL}/v1/models" 2>/dev/null)

    if [[ -n "$MODEL_INFO" ]]; then
      # Check for jq
      if ! command -v jq &>/dev/null; then
        echo ""
        echo -e "${YELLOW} jq not found; install it for model auto-detection${NC}"
      else
        echo ""
        echo -e "${WHITE}Loaded model(s):${NC}"
        MODEL_COUNT=$(echo "$MODEL_INFO" | jq '.data | length')

        # Store models in an array
        MODELS=()
        while IFS= read -r line; do
          MODELS+=("$line")
        done < <(echo "$MODEL_INFO" | jq -r '.data[].id')

        # Print models with numbering
        for i in "${!MODELS[@]}"; do
          if [[ "$MODEL_COUNT" -eq 1 ]]; then
            echo -e " ${GREEN}✔${NC} ${BOLD}${MODELS[$i]}${NC}"
          else
            echo -e " ${WHITE}$((i+1)).${NC} ${MODELS[$i]}"
          fi
        done

        # If exactly one model, use it
        if [[ "$MODEL_COUNT" -eq 1 ]]; then
          MODEL="${MODELS[0]}"
          echo ""
          echo -e "${CYAN}Automatic model selection:${NC} Using ${BOLD}${MODEL}${NC}"
          echo ""
          echo -e "${GREEN} Launching Claude Code...${NC}"

          export ANTHROPIC_BASE_URL="${LCC_BASE_URL}"
          export ANTHROPIC_AUTH_TOKEN="lyrn"
          export ANTHROPIC_API_KEY=""
          export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

          exec claude --model "$MODEL" "$@"
        fi
      fi
    fi
  else
    echo -e "${RED} Cannot reach LYRN Anthropic Proxy at ${LCC_BASE_URL}${NC}"
    echo ""
    echo -e "${WHITE}Make sure you've started the proxy in the LYRN Dashboard.${NC}"
  fi

  echo ""
  echo -e "${WHITE}Examples:${NC}"
  echo -e "  ${GREEN}lcc lyrn-model${NC}"
  echo -e "  ${GREEN}lcc my-model -p${NC}     # pass extra flags to claude"
  echo ""
  echo -e "${WHITE}Override host/port:${NC}"
  echo -e "  ${CYAN}LCC_HOST=10.0.0.5 LCC_PORT=9090 lcc mymodel${NC}"
  exit 0
fi

# Launch Claude Code with the specified model
MODEL="$1"
shift # remaining args pass through to claude

echo -e "${GREEN}Launching${NC} ${BOLD}Claude Code${NC} -> ${CYAN}${LCC_HOST}:${LCC_PORT}${NC} / ${MAGENTA}${BOLD}${MODEL}${NC}"

export ANTHROPIC_BASE_URL="${LCC_BASE_URL}"
export ANTHROPIC_AUTH_TOKEN="lyrn"
export ANTHROPIC_API_KEY=""
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

exec claude --model "$MODEL" "$@"