# Application Answer Prompt

Draft an application response using only supported stories and facts.

Constraints:
- Keep answers concise and defensible.
- Use 1 concrete story when useful.
- Avoid generic enthusiasm.
- Tie the answer to the company or role when possible.
- Do not mention tools or outcomes unless they are supported by the truth model or story bank.

Output JSON:
{
  "answer": "...",
  "supporting_story_ids": ["..."]
}
