# Local Graphify setup

Installed 22 November 2026 from Graphify-Labs/graphify at commit
3671f31124fdb1de4ec4e485b1bcd7059726a5f3. Graphify reports version 0.9.115.
The CLI and its 31 packages are isolated in .tools/graphify-venv. Its Python is
3.12.16, downloaded under .tools/python after the system's Python 3.11.3 was
below Graphify's supported minimum and the registered 3.12 path was missing.
The project agent skill is registered under .agents/skills/graphify.

## Use

Run from this repository in PowerShell.

```powershell
.\scripts\graphify.ps1 --version
.\scripts\graphify.ps1 query "IntegratedNews" --budget 1000
.\scripts\graphify.ps1 explain IntegratedNews
.\scripts\graphify.ps1 update .
```

For a fresh local code extraction and rendered report, run these sequentially.

```powershell
.\scripts\graphify.ps1 extract . --code-only --max-workers 2
.\scripts\graphify.ps1 cluster-only .
```

The wrapper defaults GRAPHIFY_BACKEND to none for its invocation, restores the
previous environment afterward, and invokes this installation directly. It
does not require a global PATH change. The installed skill's interpreter record
is graphify-out/.graphify_python. Tooling and generated graph outputs are ignored
by Git. The launcher, ignore rules and this guide can be reviewed independently
of the pre-existing application changes.

## Outputs and boundaries

- graphify-out/graph.html is the interactive viewer. The generated page currently
  loads the pinned vis-network 9.1.6 library from unpkg.com. Its first load needs
  that library available to the browser.
- graphify-out/graph.json contains the versioned graph, confidence labels and
  source locations.
- graphify-out/GRAPH_REPORT.md contains hubs, communities, import-cycle results
  and suggested investigation questions.
- manifest.json records indexed file hashes. The report's commit identifier
  alone cannot identify this uncommitted working tree. Use the manifest for its
  actual file versions.

The completed run indexes supported code locally. Documentation, papers and
images were excluded from semantic extraction. CSS is unsupported by this scan.
Environment files, private data, databases, credentials and the tool installation
are excluded using .graphifyignore and .gitignore.

The report records zero LLM input/output tokens. AST-inferred relationships are
static analysis results. Report language describing them as model-reasoned does
not mean this run called a model. An absent directed graph path can reflect
unresolved dynamic Python dispatch. It cannot establish a missing application
connection. Community cohesion and suggested refactors need source review.

## Verified run

The final incremental graph, including the local PowerShell launcher, contains
1,476 nodes, 4,402 edges and 62 communities. Integrity checks found zero duplicate
node IDs or missing edge endpoints. Source paths were checked against the
private/tooling exclusions. The generated report records no detected import
cycles and zero LLM tokens. Its low community cohesion is a navigation signal,
not a measured application defect.

Local query and explain commands return source locations. A directed path from
AutoSelector to PaperEngine was unresolved; the undirected query found a route
through shared tests. That route describes the graph's extraction, not the
complete runtime call path.

The generated viewer passed a headless Chromium check. The graph canvas rendered,
search accepted IntegratedNews, and there were no page errors. The browser test
allowed only local files and the single pinned visualization-library GET.
graphify-out/graph-preview.png records the rendered view. Dependency verification
reported all 31 installed packages compatible.

Independent installation/code-graph review scored 9/10. Documentation semantics,
unsupported CSS and actual trading behavior remain outside this code-only run.

Application code, broker credentials, market sessions and trading rules were
outside this installation task. No claim of profitability follows from a graph.
