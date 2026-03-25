"""
Example 5: LNTL Encoding
Demonstrates the LLM-Native Tool Language (LNTL) encoding format.

LNTL replaces JSON tool results with high-signal, low-noise encoding
optimized for LLM attention. See docs/lntl_spec.md for the full spec.

This example shows:
1. Converting tool results from JSON to LNTL
2. Building an Action Ledger in LNTL format
3. The verification prompt using LNTL
"""


def lntl(status: str, tool: str, target: str, **meta) -> str:
    """Encode a tool result in LNTL format.

    Args:
        status: OK, FAIL, PARTIAL, WAIT, or SKIP
        tool: Tool name (lowercase, underscores OK)
        target: Where the result went (email, file path, URL, etc.)
        **meta: Key-value metadata pairs

    Returns:
        Single-line LNTL string
    """
    line = f"{status} {tool}->{target}"
    if meta:
        pairs = " ".join(f"{k}:{v}" for k, v in meta.items())
        line += f" [{pairs}]"
    return line


def lntl_ledger(entries: list, instruction: str = "match LEDGER. FAIL=say failed. OK=say done.") -> str:
    """Build a full LNTL ledger block for verification pass.

    Args:
        entries: List of LNTL result lines
        instruction: What the model should do with the ledger

    Returns:
        Multi-line LNTL ledger string
    """
    lines = ["LEDGER:"]
    for entry in entries:
        lines.append(f"  {entry}")
    lines.append(f"RESPOND: {instruction}")
    return "\n".join(lines)


# --- Demo ---

if __name__ == "__main__":

    # 1. Individual tool results in LNTL
    print("=== Tool Results (LNTL) ===\n")

    results = [
        lntl("OK", "web_search", "ICC+cricket+rankings", results="5"),
        lntl("OK", "create_excel", "rankings.xlsx", bytes="4096", workspace="97"),
        lntl("FAIL", "send_email", "prashanth@knobly.com", code="404", reason="endpoint_missing"),
        lntl("OK", "create_pdf", "report.pdf", bytes="15200"),
        lntl("PARTIAL", "send_email", "team@company.com", sent="3/5", bounced="2"),
        lntl("WAIT", "deploy", "production", job_id="7831"),
        lntl("SKIP", "send_whatsapp", "user", reason="no_number_configured"),
    ]

    for r in results:
        print(f"  {r}")

    # 2. Compare with JSON
    print("\n=== Same result in JSON vs LNTL ===\n")

    json_result = '''{
    "success": false,
    "error": "API returned 404 Not Found",
    "tool": "send_email",
    "target": "prashanth@knobly.com"
}'''

    lntl_result = lntl("FAIL", "send_email", "prashanth@knobly.com",
                        code="404", reason="not_found")

    print(f"  JSON ({len(json_result.split())} tokens):")
    print(f"    {json_result}")
    print()
    print(f"  LNTL ({len(lntl_result.split())} tokens):")
    print(f"    {lntl_result}")

    # 3. Build verification ledger
    print("\n=== Verification Ledger ===\n")

    ledger = lntl_ledger([
        lntl("OK", "web_search", "ICC+rankings", results="5"),
        lntl("OK", "create_excel", "rankings.xlsx", workspace="97"),
        lntl("FAIL", "send_email", "prashanth@knobly.com", code="404", reason="endpoint_missing"),
    ])

    print(ledger)

    # 4. Token efficiency
    print("\n=== Token Efficiency ===\n")

    json_tokens = 25   # typical for a single JSON tool result
    lntl_tokens = 8    # same info in LNTL
    savings = (1 - lntl_tokens / json_tokens) * 100

    print(f"  JSON: ~{json_tokens} tokens per result")
    print(f"  LNTL: ~{lntl_tokens} tokens per result")
    print(f"  Savings: {savings:.0f}% fewer tokens")
    print(f"  In a 7-tool session: {json_tokens*7} vs {lntl_tokens*7} tokens")
    print(f"  That's {json_tokens*7 - lntl_tokens*7} tokens freed for actual content")
