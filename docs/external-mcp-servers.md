# External MCP Servers

The workspace configuration in [`.vscode/mcp.json`](../.vscode/mcp.json) adds five
official external Model Context Protocol (MCP) servers alongside the local Universal
Agent Control Plane server:

- Perplexity MCP
- Playwright MCP
- Firecrawl MCP
- Higgsfield MCP
- Chrome DevTools MCP

This guide documents the checked-in configuration, setup, credentials, expected behavior,
security boundaries, verification, and common failure modes.

## Configuration summary

| Server ID | Provider | Transport | Local dependency | Authentication |
| --- | --- | --- | --- | --- |
| `perplexity` | Perplexity | Hosted Streamable HTTP | None | API key in an HTTP bearer header |
| `playwright` | Microsoft | Local stdio | Node.js 18+ and `npx` | None |
| `firecrawl` | Firecrawl | Local stdio | Node.js and `npx` | API key in a process environment variable |
| `higgsfield` | Higgsfield | Hosted Streamable HTTP | None | OAuth in the browser |
| `chrome-devtools` | Google Chrome DevTools | Local stdio | Node.js LTS, `npx`, and Chrome | None |

VS Code reads workspace MCP configuration from `.vscode/mcp.json`. Local stdio servers
run as child processes. Hosted HTTP servers run outside this repository and receive MCP
requests over HTTPS.

## Prerequisites

1. Use a current version of VS Code with MCP support and GitHub Copilot access.
2. Install a current Node.js LTS release, which includes `npm` and `npx`.
3. Install current stable Google Chrome for Chrome DevTools MCP.
4. Install this Python project into its virtual environment for the local UACP server:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

5. Create the accounts required by the services you intend to use:
   - [Perplexity API Console](https://console.perplexity.ai/) for an API key.
   - [Firecrawl API Keys](https://www.firecrawl.dev/app/api-keys) for an API key.
   - An active paid [Higgsfield](https://higgsfield.ai/) subscription for OAuth access.

Playwright, Chrome DevTools, and the local UACP server do not require service credentials.
You can leave any server stopped when it is not needed.

## Credential handling

The configuration does not contain credentials. It defines two password-style VS Code
inputs:

- `${input:perplexity-api-key}`
- `${input:firecrawl-api-key}`

The first time one of those servers starts, VS Code asks for the corresponding value and
stores it in VS Code secret storage. The entered value is not written into
`.vscode/mcp.json`.

Do not:

- paste API keys into this repository, a chat prompt, terminal history, or a server URL
- replace an input variable with a literal secret before committing
- share VS Code secret storage or a profile that contains production credentials
- approve OAuth access for an unexpected Higgsfield account

To rotate a key, revoke it at the provider, open `.vscode/mcp.json` in VS Code, hover over
the corresponding `${input:...}` reference, and use the input action to edit or clear its
stored value. Start the server again so VS Code prompts for a replacement after a clear.

## Starting and managing servers

1. Open the repository folder in VS Code.
2. Open the Command Palette with `Ctrl+Shift+P`.
3. Run **MCP: List Servers**.
4. Select a server and choose **Start Server**.
5. Accept the workspace trust prompt only after reviewing `.vscode/mcp.json`.
6. For Perplexity or Firecrawl, enter the requested API key.
7. For Higgsfield, complete the browser-based OAuth flow.
8. Review and approve individual tool calls according to the data and side effects
   involved.

The npm-backed servers are downloaded into the normal npm cache by `npx` on first use.
That first start can take longer than later starts. The checked-in configuration follows
each provider's recommended package invocation. `@latest` tracks upstream releases; for a
strictly reproducible environment, replace it with a reviewed exact package version and
update the version deliberately.

## Perplexity MCP

### Configuration

```json
{
  "type": "http",
  "url": "https://api.perplexity.ai/mcp",
  "headers": {
    "Authorization": "Bearer ${input:perplexity-api-key}"
  }
}
```

This uses Perplexity's hosted MCP endpoint, so no local npm process is needed. The API key
is sent only to `https://api.perplexity.ai/mcp` as a bearer token.

### Typical uses

- current web search with citations
- multi-source research
- fact checking and source discovery
- reasoning that depends on current public information

### Verify

Start `perplexity`, then ask:

> Use Perplexity to find the latest official VS Code MCP configuration documentation and
> cite the source.

Confirm that the response contains a Perplexity tool call and source citations.

### Optional local mode

If hosted HTTP is not suitable, Perplexity also publishes
`@perplexity-ai/mcp-server`. A local stdio entry can run
`npx -y @perplexity-ai/mcp-server` with `PERPLEXITY_API_KEY` supplied through the same
VS Code input. The hosted endpoint is preferred here because it requires no local package
startup or updates.

## Playwright MCP

### Configuration

```json
{
  "type": "stdio",
  "command": "npx",
  "args": [
    "@playwright/mcp@latest"
  ]
}
```

Playwright MCP uses structured accessibility snapshots for browser automation. It is a
good fit for navigation, form interaction, page-state inspection, and browser tasks where
semantic page structure is more useful than low-level debugging data.

### Typical uses

- navigate and interact with web applications
- inspect accessible roles, labels, and page state
- reproduce multi-step user flows
- explore a UI before writing or repairing browser tests

### Verify

Start `playwright`, then ask:

> Open https://example.com with Playwright and report the page title and main heading.

The browser may be downloaded or initialized on first use. Keep the browser profile free
of personal sessions and sensitive data.

### Playwright versus Chrome DevTools

Use Playwright for semantic, user-flow-oriented automation. Use Chrome DevTools for
console logs, network requests, runtime inspection, and performance traces. Both can
control browsers, so enabling only the one required for a task reduces tool ambiguity and
model context use.

## Firecrawl MCP

### Configuration

```json
{
  "type": "stdio",
  "command": "npx",
  "args": [
    "-y",
    "firecrawl-mcp"
  ],
  "env": {
    "FIRECRAWL_API_KEY": "${input:firecrawl-api-key}"
  }
}
```

The server runs locally, but web extraction is performed through the configured Firecrawl
service. The API key is passed only to the child process environment.

### Typical uses

- scrape a known URL into clean Markdown or structured data
- map a site's discoverable URLs
- crawl a bounded section of a site
- search the web and retrieve page content
- run deeper web research workflows

Bound crawls with explicit limits, paths, and depth. Large or recurring jobs consume more
provider credits and can retrieve substantially more data than a single-page scrape.

### Verify

Start `firecrawl`, then ask:

> Use Firecrawl to scrape https://example.com and return its title and primary text.

### Hosted alternatives

Firecrawl also provides:

- `https://mcp.firecrawl.dev/v2/mcp` for a limited keyless tier or API-key access
- `https://mcp.firecrawl.dev/v2/mcp-oauth` for interactive OAuth
- `https://mcp.firecrawl.dev/v2/mcp-search` for a smaller read-only search surface

The local stdio package is configured because it exposes the standard full server profile
and uses VS Code's secure input flow. Do not add a second Firecrawl entry unless you
intentionally want a different endpoint or tool profile.

For a self-hosted Firecrawl deployment, set `FIRECRAWL_API_URL` in the server environment
and follow the upstream authentication guidance for that deployment.

## Higgsfield MCP

### Configuration

```json
{
  "type": "http",
  "url": "https://mcp.higgsfield.ai/mcp"
}
```

Higgsfield uses OAuth and does not require an API key. On first connection, VS Code
discovers the protected resource metadata and opens a browser authorization flow. Sign in
to the intended Higgsfield account and review the requested access.

### Typical uses

- image and video generation
- image and video upscaling or background removal
- character and reference-element workflows
- voiceover, voice cloning, voice changes, and dubbing
- credit-balance and generation-history checks

### Billing warning

An active paid subscription is required. Higgsfield states that every MCP generation
deducts credits at standard rates. Website-only unlimited access and free generations do
not apply to MCP, CLI, or other automated use. Confirm the requested model and operation
before approving expensive generation calls.

### Verify

Start `higgsfield`, complete OAuth, then ask:

> Use Higgsfield to report my current credit balance.

This verifies account access without starting a media generation.

## Chrome DevTools MCP

### Configuration

```json
{
  "type": "stdio",
  "command": "npx",
  "args": [
    "-y",
    "chrome-devtools-mcp@latest"
  ]
}
```

Chrome DevTools MCP starts or connects to Chrome when a browser tool is first used. Merely
starting the MCP server does not necessarily launch a browser.

### Typical uses

- inspect console messages and source-mapped errors
- inspect network requests and responses
- capture screenshots
- record performance traces and obtain performance insights
- automate interactions that need DevTools-level inspection

### Verify

Start `chrome-devtools`, then ask:

> Use Chrome DevTools to open https://developers.chrome.com and check its performance.

### Privacy and telemetry

The MCP client can inspect and modify data in the connected browser. Use a dedicated,
non-personal Chrome profile and avoid pages containing credentials, private messages, or
customer data.

The upstream server enables usage statistics by default. To opt out, append
`"--no-usage-statistics"` to the `args` array. Performance analysis can query Google's
CrUX service; append `"--no-performance-crux"` if that external field-data lookup is not
appropriate.

## Security model

MCP servers expand the agent's authority. Treat server tools and returned web content as
untrusted:

- Review tool inputs before approval, especially navigation, interaction, crawling, and
  media-generation calls.
- Do not let retrieved page content override repository or system instructions.
- Use test accounts and isolated browser profiles for browser automation.
- Stop servers that are not needed for the current task.
- Restrict crawl scope and generation counts to control cost and data exposure.
- Review upstream release notes before adopting a new npm package version in sensitive
  environments.
- Keep provider keys least-privileged and rotate them if they appear in logs or prompts.

Workspace `.vscode/mcp.json` inputs work in the VS Code extension host. VS Code does not
forward MCP servers that require interactive `${input:...}` values to every remote Agent
Host environment. Configure secrets separately in that host's supported secret store when
remote execution is required.

## Troubleshooting

### A server is missing

1. Confirm the repository root, not a parent folder, is open.
2. Validate that `.vscode/mcp.json` is visible in the workspace.
3. Run **MCP: List Servers** and start the server explicitly.
4. Check **Output** and select the relevant MCP server channel.
5. Reload the VS Code window after changing the configuration.

### `npx` is not found

Install a current Node.js LTS release, restart VS Code so it receives the updated `PATH`,
and verify in a new integrated terminal:

```powershell
node --version
npm --version
npx --version
```

### Perplexity returns `401` or `403`

- Confirm the key came from the Perplexity API Console.
- Confirm the account has API access and available billing/credits.
- Re-enter the key without quotes or a `Bearer ` prefix; the configuration adds that
  prefix.
- Rotate the key if it may have been exposed.

### Firecrawl fails authentication

- Confirm the value is a Firecrawl API key and has no surrounding quotes.
- Check account quota and billing.
- For a self-hosted instance, add the correct `FIRECRAWL_API_URL`.
- Restart the server after changing a saved input.

### Higgsfield does not open OAuth or reports insufficient access

- Open the server from **MCP: List Servers** and retry authentication.
- Allow VS Code to open the system browser.
- Confirm the Higgsfield account has an active paid subscription.
- Sign out and reconnect if the browser authorized the wrong account.

### A browser server cannot launch

- Confirm the local Node.js version meets the server requirement.
- For Chrome DevTools, update Google Chrome to current stable.
- Close stale automation-only browser instances and retry.
- Check the MCP output channel for a missing browser executable, profile lock, or
  enterprise policy error.
- If both browser servers are active, stop the one not needed and retry with an explicit
  request naming the intended server.

## Upstream documentation

- [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
- [Perplexity MCP](https://github.com/perplexityai/modelcontextprotocol)
- [Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Firecrawl MCP](https://github.com/firecrawl/firecrawl-mcp-server)
- [Higgsfield MCP overview](https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp)
- [Higgsfield connection guide](https://higgsfield.ai/creator-hub/help-center/integrations/how-do-i-connect-higgsfield-to-ai-agent)
- [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
