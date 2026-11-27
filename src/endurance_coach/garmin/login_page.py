"""Mobile page for Garmin reauthorization."""

from __future__ import annotations

LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Garmin sign-in</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, sans-serif;
    margin: 0;
    padding: 1.25rem;
    line-height: 1.4;
  }
  main { max-width: 28rem; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin: 0 0 0.5rem; }
  p { margin: 0.4rem 0 1rem; }
  label { display: block; font-weight: 600; margin: 0.8rem 0 0.3rem; }
  input {
    width: 100%;
    box-sizing: border-box;
    font-size: 1.05rem;
    padding: 0.7rem;
  }
  button {
    margin-top: 1rem;
    width: 100%;
    font-size: 1.05rem;
    padding: 0.8rem;
  }
  .status { min-height: 1.4rem; margin-top: 1rem; }
  .hidden { display: none; }
</style>
</head>
<body>
<main>
  <h1>Garmin sign-in</h1>
  <p>This page is on your server. Garmin sign-in runs here, on this computer. Type your Garmin email, password, and the verification code if Garmin asks for one.</p>
  <p>The password is used only for this sign-in. It is not saved, not written to disk, and not sent to the alert service. The alert that opened this page does not contain the password.</p>
  <p>Leave the server VPN off until this finishes.</p>
  <form id="credentials">
    <label for="email">Garmin email or username</label>
    <input id="email" name="email" autocomplete="username" required>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
  </form>
  <form id="code" class="hidden">
    <label for="mfa">Verification code</label>
    <input id="mfa" name="code" inputmode="numeric" autocomplete="one-time-code" required>
    <button type="submit">Submit code</button>
  </form>
  <p id="status" class="status" role="status"></p>
</main>
<script>
const statusEl = document.getElementById("status")
const credentials = document.getElementById("credentials")
const codeForm = document.getElementById("code")
const query = new URLSearchParams(location.search)
const hash = new URLSearchParams(location.hash.replace(/^#/, ""))
const grant = hash.get("t") || query.get("t") || ""
if (grant && location.search) {
  history.replaceState(null, "", location.pathname + "#t=" + encodeURIComponent(grant))
}
let loginId = ""

function setStatus(text) { statusEl.textContent = text }

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Garmin-Login-Grant": grant
    },
    body: JSON.stringify(body)
  })
  let payload = {}
  try { payload = await response.json() } catch (error) { payload = {} }
  if (!response.ok) {
    const detail = payload.detail
    throw new Error(typeof detail === "string" ? detail : "Sign-in failed.")
  }
  return payload
}

if (!grant) {
  credentials.classList.add("hidden")
  setStatus("Open this page from the Garmin alert on your phone.")
}

credentials.addEventListener("submit", async (event) => {
  event.preventDefault()
  setStatus("Signing in…")
  credentials.querySelector("button").disabled = true
  try {
    const result = await post("/api/v1/garmin/login", {
      email: document.getElementById("email").value,
      password: document.getElementById("password").value
    })
    document.getElementById("password").value = ""
    if (result.status === "needs_mfa") {
      loginId = result.login_id
      credentials.classList.add("hidden")
      codeForm.classList.remove("hidden")
      setStatus(result.message)
      document.getElementById("mfa").focus()
    } else {
      credentials.classList.add("hidden")
      setStatus(result.message)
    }
  } catch (error) {
    setStatus(error.message)
  } finally {
    credentials.querySelector("button").disabled = false
  }
})

codeForm.addEventListener("submit", async (event) => {
  event.preventDefault()
  setStatus("Checking the code…")
  codeForm.querySelector("button").disabled = true
  try {
    const result = await post("/api/v1/garmin/login/" + encodeURIComponent(loginId) + "/code", {
      code: document.getElementById("mfa").value
    })
    codeForm.classList.add("hidden")
    setStatus(result.message)
  } catch (error) {
    setStatus(error.message)
  } finally {
    codeForm.querySelector("button").disabled = false
  }
})
</script>
</body>
</html>
"""
