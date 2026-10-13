#!/usr/bin/env bash
# glm_probe.sh - one tiny request per GLM key, prints HTTP status and the error
# body head. Never prints the key. Keys come from /root/.glm_keys (one per line)
# or, if that file is absent, from ANTHROPIC_AUTH_TOKEN in /root/.glm_env.
# Run:  bash /root/qc/tools/glm_probe.sh
BASE=${GLM_BASE_URL:-http://34.41.10.8:4000}
MODEL=${GLM_MODEL:-glm-5.2}
keys=()
if [ -s /root/.glm_keys ]; then
  while IFS= read -r k; do k=$(echo "$k" | tr -d '\r[:space:]'); [ -n "$k" ] && [ "${k:0:1}" != "#" ] && keys+=("$k"); done < /root/.glm_keys
elif [ -f /root/.glm_env ]; then
  # shellcheck disable=SC1091
  source /root/.glm_env; [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ] && keys+=("$ANTHROPIC_AUTH_TOKEN")
fi
[ "${#keys[@]}" -eq 0 ] && { echo "no keys found in /root/.glm_keys or /root/.glm_env"; exit 2; }
i=0
for k in "${keys[@]}"; do
  i=$((i+1))
  body=$(curl -s -m 40 -w '\n%{http_code}' "$BASE/v1/messages" \
    -H "Authorization: Bearer $k" -H "x-api-key: $k" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
    -d "{\"model\":\"$MODEL\",\"max_tokens\":5,\"messages\":[{\"role\":\"user\",\"content\":\"reply ok\"}]}")
  code=$(echo "$body" | tail -1); msg=$(echo "$body" | head -n -1 | tr -d '\n' | cut -c1-140)
  case "$code" in
    200) verdict="OK, has quota";;
    402) verdict="OUT OF QUOTA (shared upstream budget or this key's budget exhausted)";;
    401|403) verdict="key rejected";;
    429) verdict="rate limited right now (has quota, too fast)";;
    *) verdict="other";;
  esac
  printf "key %d (…%s): HTTP %s  %s\n     %s\n" "$i" "${k: -4}" "$code" "$verdict" "$msg"
done
