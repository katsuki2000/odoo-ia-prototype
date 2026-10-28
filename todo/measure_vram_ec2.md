# Mesure VRAM -- a copier-coller sur l'EC2

## Etape 1 : creer le script (coller ce bloc en entier)

```bash
cat > /tmp/measure_vram.sh << 'ENDOFSCRIPT'
#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "ERROR: This script must be run as root or with sudo." >&2
    exit 1
fi

DROPIN_DIR="${DROPIN_DIR:-/etc/systemd/system/ollama.service.d}"
DROPIN_FILE="${DROPIN_DIR}/zz-vram-measure.conf"
RESULTS_FILE="${RESULTS_FILE:-/tmp/vram_results.csv}"
OLLAMA="${OLLAMA_HOST:-http://127.0.0.1:11434}"

MODELS=("qwen3:8b" "qwen3:14b" "gpt-oss:20b" "mistral-small3.2:24b" "qwen3:30b-a3b")
EMBED_MODEL="bge-m3:latest"

CONFIGS=("1:32768" "3:16384" "3:32768")
VRAM_LIMIT_MIB=22528

cleanup() {
    local exit_code=$?
    echo ""
    echo "========================================="
    echo "  Cleanup: restoring baseline configuration"
    echo "========================================="
    if [ -f "${DROPIN_FILE}" ]; then
        rm -f "${DROPIN_FILE}"
        systemctl daemon-reload
        systemctl restart ollama || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

wait_for_ollama() {
    local retries=0
    while ! curl -sf "${OLLAMA}/" >/dev/null 2>&1; do
        sleep 1
        retries=$((retries + 1))
        if [ "$retries" -ge 60 ]; then
            echo "ERROR: Ollama did not start within 60s" >&2
            return 1
        fi
    done
    sleep 30
}

unload_all() {
    local models_loaded
    models_loaded=$(curl -sf "${OLLAMA}/api/ps" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    print(m['name'])
" 2>/dev/null || true)
    for m in $models_loaded; do
        curl -sf "${OLLAMA}/api/generate" -d "{\"model\":\"${m}\",\"keep_alive\":0}" >/dev/null 2>&1 || true
    done
    sleep 2
}

load_model() {
    local model="$1"
    curl -sf "${OLLAMA}/api/generate" -d "{\"model\":\"${model}\",\"keep_alive\":-1}" >/dev/null 2>&1
    sleep 3
}

read_ps() {
    curl -sf "${OLLAMA}/api/ps" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    name = m['name']
    size = m.get('size', 0)
    size_vram = m.get('size_vram', 0)
    print(f'{name}|{size}|{size_vram}')
" 2>/dev/null
}

get_gpu_used_mib() {
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' '
}

get_layers_info() {
    journalctl -u ollama --since "2 minutes ago" --no-pager 2>/dev/null \
        | grep "load_tensors: offloaded" | tail -2 || echo "no_layer_info"
}

sep() { echo "-------------------------------------------"; }

echo "========================================="
echo "  VRAM Measurement Bench (Section 1637)"
echo "  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "========================================="
echo ""

if ! command -v nvidia-smi &>/dev/null; then
    echo "ERROR: nvidia-smi not found" >&2
    exit 1
fi
if ! curl -sf "${OLLAMA}/" >/dev/null 2>&1; then
    echo "ERROR: Ollama not reachable at ${OLLAMA}" >&2
    exit 1
fi

nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

echo "config,model,parallel,context,size_bytes,size_vram_bytes,gpu_used_mib,layers_info,embed_size_vram,verdict" > "${RESULTS_FILE}"

for config in "${CONFIGS[@]}"; do
    IFS=':' read -r parallel context <<< "$config"

    echo ""
    echo "========================================="
    echo "  Config: NUM_PARALLEL=${parallel}, CONTEXT_LENGTH=${context}"
    echo "========================================="

    cat > "${DROPIN_FILE}" << DROPIN
[Service]
Environment="OLLAMA_NUM_PARALLEL=${parallel}"
Environment="OLLAMA_CONTEXT_LENGTH=${context}"
DROPIN

    systemctl daemon-reload

    for model in "${MODELS[@]}"; do
        sep
        echo "Model: ${model} | parallel=${parallel} | context=${context}"
        echo "$(date -u '+%H:%M:%S') Starting..."

        systemctl restart ollama
        wait_for_ollama
        unload_all

        echo "$(date -u '+%H:%M:%S') Loading ${model}..."
        load_model "${model}"

        echo "$(date -u '+%H:%M:%S') Loading ${EMBED_MODEL}..."
        curl -sf "${OLLAMA}/api/embed" -d "{\"model\":\"${EMBED_MODEL}\",\"input\":\"test\",\"keep_alive\":-1}" >/dev/null 2>&1
        sleep 3

        gpu_used=$(get_gpu_used_mib)
        ps_output=$(read_ps)
        layers=$(get_layers_info)

        model_size=""
        model_size_vram=""
        embed_size_vram=""
        while IFS='|' read -r name sz sv; do
            if [[ "$name" == *"bge-m3"* ]]; then
                embed_size_vram="$sv"
            else
                model_size="$sz"
                model_size_vram="$sv"
            fi
        done <<< "$ps_output"

        verdict="PASS"
        reason=""

        if [ -n "$model_size" ] && [ -n "$model_size_vram" ] && [ "$model_size_vram" -lt "$model_size" ] 2>/dev/null; then
            verdict="FAIL"
            reason="size_vram < size (partial CPU offload)"
        fi

        if [ -n "$gpu_used" ] && [ "$gpu_used" -gt "$VRAM_LIMIT_MIB" ] 2>/dev/null; then
            verdict="FAIL"
            reason="${reason:+${reason}; }gpu_used=${gpu_used} MiB > ${VRAM_LIMIT_MIB} MiB"
        fi

        if [ -n "$embed_size_vram" ] && [ "$embed_size_vram" = "0" ] 2>/dev/null; then
            verdict="FAIL"
            reason="${reason:+${reason}; }bge-m3 fully on CPU"
        fi

        model_size_gb=$(python3 -c "print(f'{${model_size:-0}/1e9:.1f}')" 2>/dev/null || echo "?")
        model_vram_gb=$(python3 -c "print(f'{${model_size_vram:-0}/1e9:.1f}')" 2>/dev/null || echo "?")
        embed_vram_gb=$(python3 -c "print(f'{${embed_size_vram:-0}/1e9:.1f}')" 2>/dev/null || echo "?")

        echo ""
        echo "  size:       ${model_size_gb} GB"
        echo "  size_vram:  ${model_vram_gb} GB"
        echo "  embed_vram: ${embed_vram_gb} GB"
        echo "  GPU used:   ${gpu_used} MiB"
        echo "  Layers:     $(echo "$layers" | tail -2 | tr '\n' ' ')"
        echo "  VERDICT:    ${verdict} ${reason:+(${reason})}"
        echo ""

        layers_short=$(echo "$layers" | tail -1 | sed 's/.*load_tensors: //' | tr -d '\n')
        echo "${config},${model},${parallel},${context},${model_size:-0},${model_size_vram:-0},${gpu_used:-0},\"${layers_short}\",${embed_size_vram:-0},${verdict}" >> "${RESULTS_FILE}"
    done
done

rm -f "${DROPIN_FILE}"
systemctl daemon-reload
systemctl restart ollama
wait_for_ollama

echo ""
echo "Ollama restored to baseline (override.conf only)."
echo ""
echo "Results saved to: ${RESULTS_FILE}"
echo ""
echo "=== CSV Summary ==="
column -t -s',' "${RESULTS_FILE}" 2>/dev/null || cat "${RESULTS_FILE}"
echo ""
echo "Done at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
ENDOFSCRIPT
```

## Etape 2 : lancer le script

```bash
sudo bash /tmp/measure_vram.sh 2>&1 | tee /tmp/vram_results.txt
```

## Etape 3 : recuperer les resultats

```bash
cat /tmp/vram_results.csv
```
