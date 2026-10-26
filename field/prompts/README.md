# Glimmer field prompts

Placeholder until the local model is benchmarked on the target laptop
(RTX 3080 16GB, llama.cpp, Q4_K_M, 4K context, ~250-token JSON outputs).

Prompt contract (to freeze after benchmarking): input is photo + GPS +
spoken/typed Lao notes; output is exactly one JSON object matching the
`finds` table (object type, condition, estimated size, risk flag, location).
Below ~12 tok/s the demo uses the pre-recorded triage clip and says so —
never fake a live run.
