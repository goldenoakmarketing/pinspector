# Connect your local model to PinSpector

PinSpector connects to a model server running on your own computer. The public
download does not include a model, install a runtime, or start it for you. Website
and Maps collection can run without AI; model assessments need this connection.
Your Veriphone key is separate and is used only for phone lookups.

## Option 1: Ollama on Windows

1. Install and open Ollama using its [official Windows instructions](https://docs.ollama.com/windows).
   The Windows app normally runs in the background on port 11434.
2. Open PowerShell and run `ollama ls` to see installed models. If you already
   have a suitable local model, keep it. Qwen 2.5 7B is the model tested with
   PinSpector; other models may respond differently.
3. If you choose to download that model, run `ollama pull qwen2.5:7b`.
   This downloads model weights and needs internet access and disk space.
   Available RAM and GPU memory affect whether inference completes successfully.
4. Keep Ollama running. If using its standalone CLI instead of the Windows app,
   run `ollama serve` in a separate terminal and leave it open. Do not start a
   second server if Ollama is already running.
5. Open PinSpector and click **Settings** in the left sidebar.
6. Under **Local inference connection**, select **Ollama**. Set **Local endpoint**
   to `http://127.0.0.1:11434`, unless you deliberately configured another port.
7. Click **Detect installed models**. Choose your model under **Existing model**,
   then click **Save local connection**. Look for **Local connection saved**.

The listing command, download command, and standalone server command are described
in the [Ollama CLI reference](https://docs.ollama.com/cli).

## Option 2: an OpenAI-compatible local server

For example, in LM Studio, select a downloaded model and open the **Developer**
tab, then start the local API server. See its [local server guide](https://lmstudio.ai/docs/developer/core/server).

In PinSpector's **Settings**, select **OpenAI-compatible local server**. Enter the
server's loopback URL and port, such as `http://127.0.0.1:1234` for LM Studio's
usual port. Click **Detect installed models**, choose the returned model, and
click **Save local connection**. The adapter uses `/v1/models` and
`/v1/chat/completions`; the base URL can optionally end in `/v1`.

PinSpector currently has no local-server authentication-token field. A server
requiring a bearer token is not supported by this adapter. Keep your model server
on loopback; do not enable network sharing to make detection work. Use a downloaded
local model, not a cloud-backed model, if evidence must stay on your computer.

## Check that it works

Detection confirms the server can list models; it does not prove the model can
complete an assessment. Save the connection, run a small investigation with AI
enabled, and check its activity and assessment results. The fictional demo tests
the app workflow but does not prove a live model connection works.

Saved model settings survive restarting PinSpector. After restarting Windows,
make sure the model server is running again before requesting AI assessments.
After fixing a failed connection, retry the assessment; earlier failures do not
automatically resume. **Update investigation** runs the expanded collection again.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| Connection refused / WinError 10061 | Start the model server and verify the endpoint and port. Refreshing PinSpector cannot start the server. |
| No models found | Install a local model in your runtime, then detect again. Check that PinSpector is connected to the runtime where you installed it. |
| Unauthorized / 401 | This adapter does not support authenticated model servers. Do not paste a Veriphone key into the model endpoint. |
| Timeout or out-of-memory error | Confirm the model runs in its own runtime and that your computer has enough resources. A smaller model may run faster but can produce different results. |
| Model output rejected | The model's response did not pass evidence/format checks. This is not a finding against the business. |

Only `http://localhost`, `http://127.0.0.1`, or `http://[::1]` URLs with an explicit
port are accepted. A cloud API URL or an API key is not a local endpoint.
