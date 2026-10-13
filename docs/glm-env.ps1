# Point the claude command at the team GLM gateway for THIS PowerShell window only.
# Use:  . .\docs\glm-env.ps1     (then run python qc.py read ... in the same window)
# Needs GLM_API_KEY, saved once with:  setx GLM_API_KEY "PASTE_YOUR_KEY_HERE"  (then open a new window)
if (-not $env:GLM_API_KEY) {
    Write-Host 'GLM_API_KEY is not set. Run: setx GLM_API_KEY "PASTE_YOUR_KEY_HERE"  then open a new PowerShell window.'
    return
}
$env:ANTHROPIC_BASE_URL = "http://34.41.10.8:4000"
$env:ANTHROPIC_AUTH_TOKEN = $env:GLM_API_KEY
$env:ANTHROPIC_MODEL = "glm-5.2"
$env:ANTHROPIC_SMALL_FAST_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "glm-5.2"
# GLM answers at length; without this Claude Code stops a call at its 32,000-token output limit.
$env:CLAUDE_CODE_MAX_OUTPUT_TOKENS = "64000"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Write-Host "claude now uses the team GLM gateway in this window. Close the window to go back to your own login."
