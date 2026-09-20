param(
  [string]$ModelId = "hf_tiny_gpt2_local",
  [string]$WorkloadDescription = "I need an agent that can summarize internal engineering documents as structured JSON with citations and must not access the public internet."
)

$finch = Get-Command finch -ErrorAction SilentlyContinue
if ($finch) {
  Write-Host "Finch detected. Kriterion will build/run the evaluator image during qualification."
  python -m kriterion qualify --model-id $ModelId --workload-description $WorkloadDescription
} else {
  Write-Host "Finch not found. Running in local developer fallback mode (--allow-local-evaluator)."
  Write-Host "The evaluator_environment evidence record will be INSUFFICIENT_EVIDENCE."
  Write-Host "This path is for development only and is not valid for admission benchmarks."
  python -m kriterion qualify --model-id $ModelId --workload-description $WorkloadDescription --allow-local-evaluator --allow-strands-fallback
}