# Detect local inference without changing another application's runtime or models.
$ErrorActionPreference = 'Stop'
foreach ($modelEndpoint in @('http://127.0.0.1:11434', 'http://127.0.0.1:11436')) {
    try {
        $tags = Invoke-RestMethod -Uri "$modelEndpoint/api/tags" -TimeoutSec 2
        if ($null -ne $tags.models) {
            Write-Output "Local model service found at $modelEndpoint. Select its installed model in Settings."
            exit 0
        }
    } catch {
        # An absent runtime is optional; evidence collection can still run.
    }
}
Write-Output 'No running Ollama service detected. Start your local runtime, then use Settings > Detect installed models.'
Write-Output 'Ollama setup: https://ollama.com/download/windows'
Write-Output 'Suggested model: qwen2.5:7b. No model was downloaded or started.'
exit 0
