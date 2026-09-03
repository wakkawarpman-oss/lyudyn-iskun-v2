---
description: "Workspace boundaries, project isolation, and tactical media invariants"
globs: "*"
alwaysApply: true
---

# Rule: Strict Project Isolation & Workspace Boundary Jail

1. **ACTIVE PRODUCTION WORKSPACE ONLY:**
   - The ONLY authorized working directory for this project is:
     `/Users/gonzo/Desktop/V2/lyudyn-iskun-v2`
   - All shell commands, searches (`grep`, `rg`, `find`), file reads, and edits MUST be strictly scoped inside this directory or its subdirectories (`./`).

2. **STRICTLY EXCLUDED & OFF-LIMITS PROJECTS:**
   - The following projects are SEPARATE, PRIVATE, and MUST NEVER be inspected, scanned, grepped, opened, or read under ANY circumstances:
     * `/Users/gonzo/Desktop/АІ OFFENCE/` (Offensive intelligence - strictly forbidden)
     * `/Users/gonzo/Desktop/sovereign-tactical-intel-platform/` (External intelligence platform - strictly forbidden)
     * `/Users/gonzo/Desktop/PXY_MAP_APP/` (Separate standalone map app - strictly forbidden)
     * `/Users/gonzo/Desktop/Acheron_Integrated_v3/` (Separate integration repo - strictly forbidden)
     * Any other folder on `/Users/gonzo/Desktop/` or user home.

3. **COMMAND EXECUTION SCOPE JAIL:**
   - NEVER run unbounded global searches like `grep ... /Users/gonzo/Desktop/` or `find /Users/gonzo/`.
   - All searches MUST use relative paths `./` within `/Users/gonzo/Desktop/V2/lyudyn-iskun-v2`.

4. **EGO-BROWSER / BROWSER OPSEC ISOLATION:**
   - NEVER inspect, claim, or view tabs from user personal spaces or separate OSINT spaces (e.g., `Graylark Raven`, `GeoSpy`, personal Telegrams).
   - Browser sessions for this bot must use dedicated isolated task spaces prefixed with `iskun-` only.

5. **TACTICAL MEDIA & QUALITY STANDARDS:**
   - Map symbology standard: Military grade ONLY (pulsing red dots `🔴`, chevrons `▲`). Zero civilian airplane `✈️` or UFO `🛸` emojis.
   - Bot stress-relief: strictly authenticated audio files. No jokes, no civilian memes.
