import re

def format_raw_text(text: str):
    """
    Cleans and formats raw string content into readable multiline text.
    - Preserves natural newlines and paragraphs.
    - Adds numbering or bullets only if they are already present.
    - Removes unwanted escape sequences like \\n or extra spaces.
    """

    # 1️⃣ Unescape any literal "\n" and trim spaces
    text = text.replace("\\n", "\n").strip()

    # 2️⃣ Normalize spacing (remove extra newlines >2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 3️⃣ Split into paragraphs by double newlines
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    formatted = []

    for para in paragraphs:
        # Detect bullet-like structure
        if re.match(r"^[-*•\dA-Za-z]+\.", para.strip()):
            formatted.append(para)  # already structured, leave as is
        else:
            # Clean single newlines inside poetic lines, but keep flow
            para = re.sub(r'\s*\n\s*', '\n', para)
            formatted.append(para)

    # 4️⃣ Join paragraphs with double newlines
    return "\n\n".join(formatted)
