# Retry Prompts for Benchmark Agent

Injected when the agent is stuck or produces an incorrect answer.
Each retry escalates specificity without giving away the answer.

---

## retry_1: Insufficient Exploration

**Trigger:** Answered without reading enough files, or lacks specific file/line refs.

```
Your answer appears to be based on limited exploration. The question requires
understanding how multiple parts of the codebase interact.

Please:
1. Search for additional files related to {related_terms}.
2. Read the key implementation files (not just the README).
3. Check for tests, config files, or error handling that might clarify the behavior.
4. Then provide a revised answer with specific file and line references.
```

---

## retry_2: Hallucination Suspected

**Trigger:** Cited files that don't exist or claimed behavior not in the code.

```
Some files or behaviors you mentioned could not be verified in the codebase.
Please:
1. Verify each file path you cited actually exists.
2. Re-read the files you mentioned to confirm your claims.
3. If a file does not exist, retract the claim and search for the correct file.
4. Provide a corrected answer based only on verified evidence.
```

---

## retry_3: Wrong Conclusion

**Trigger:** Read right files but drew an incorrect conclusion.

```
You found the right files, but your conclusion does not match what the code shows.
Please:
1. Re-read the specific functions/types you identified.
2. Trace the data flow more carefully — who calls whom and with what arguments?
3. Check for edge cases or error paths that might change the behavior.
4. Provide a corrected answer.
```

---

## retry_4: Stuck / No Progress

**Trigger:** Looping, repeating same searches, or not advancing.

```
You seem to be repeating the same search patterns without making progress.
Try a different strategy:
1. Look at the directory structure with Glob to find packages/modules you haven't explored.
2. Search for the main entrypoint or composition root and work outward from there.
3. Check tests — they often show expected behavior and call patterns.
4. If truly blocked, state what you have found and what remains unknown.
```
