import re
from typing import List, Optional, Set

# Comprehensive stopwords list
STOPWORDS: Set[str] = {
    # Articles
    'a', 'an', 'the',
    
    # Pronouns
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves',
    'you', 'your', 'yours', 'yourself', 'yourselves',
    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself',
    'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
    
    # Prepositions
    'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between',
    'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under',
    
    # Conjunctions
    'and', 'but', 'or', 'nor', 'so', 'yet',
    
    # Common verbs
    'is', 'am', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'should', 'could', 'may', 'might', 'must', 'can',
    
    # Question words (keep selective ones, remove generic)
    'what', 'which', 'who', 'when', 'where', 'why',
    
    # Common adverbs
    'not', 'no', 'yes', 'very', 'too', 'also', 'just', 'only',
    'more', 'most', 'much', 'many', 'some', 'any', 'all', 'each',
    'every', 'both', 'few', 'several', 'other', 'another',
    
    # Contractions & casual
    "i'm", "you're", "he's", "she's", "it's", "we're", "they're",
    "i've", "you've", "we've", "they've",
    "i'll", "you'll", "he'll", "she'll", "we'll", "they'll",
    "isn't", "aren't", "wasn't", "weren't",
    "hasn't", "haven't", "hadn't",
    "doesn't", "don't", "didn't",
    "won't", "wouldn't", "can't", "couldn't",
    "shouldn't", "mightn't", "mustn't",
    
    # Others
    'this', 'that', 'these', 'those',
    'then', 'than', 'as', 'if', 'because',
    'there', 'here', 'now', 'such'
}

def extract_keywords(text: str, min_word_length: int = 2, preserve_phrases: bool = False) -> str:
    """
    Extract keywords from text by removing stopwords and common filler words.
    Optimized for Pinecone semantic search.
    
    Args:
        text: Input search text
        min_word_length: Minimum word length to keep (default: 2)
        preserve_phrases: If True, keeps quoted phrases intact (default: False)
    
    Returns:
        Cleaned keyword string joined by spaces
    
    Examples:
        >>> extract_keywords("How do I create a React component?")
        "create React component"
        
        >>> extract_keywords("What is the best way to learn Python?")
        "best way learn Python"
        
        >>> extract_keywords("Tell me about machine learning algorithms")
        "machine learning algorithms"
    """
    if not text or not text.strip():
        return ""
    
    # Preserve quoted phrases if enabled
    preserved_phrases = []
    if preserve_phrases:
        # Extract content within quotes
        quote_pattern = r'"([^"]+)"'
        preserved_phrases = re.findall(quote_pattern, text)
        # Remove quotes from original text
        text = re.sub(quote_pattern, '', text)
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove special characters but keep alphanumeric and spaces
    # Keep hyphens for compound words (e.g., "machine-learning")
    text = re.sub(r'[^\w\s-]', ' ', text)
    
    # Split into words
    words = text.split()
    
    # Filter: remove stopwords and short words
    keywords = [
        word for word in words 
        if word not in STOPWORDS 
        and len(word) >= min_word_length
        and not word.isdigit()  # Remove pure numbers (optional)
    ]
    
    # Add back preserved phrases
    if preserve_phrases and preserved_phrases:
        keywords.extend(preserved_phrases)
    
    # Join and return
    return ' '.join(keywords)


def extract_keywords_advanced(
    text: str, 
    min_word_length: int = 2,
    keep_technical_terms: bool = True,
    max_keywords: Optional[int] = None
) -> str:
    """
    Advanced keyword extraction with technical term preservation.
    
    Args:
        text: Input search text
        min_word_length: Minimum word length to keep
        keep_technical_terms: Preserve programming/technical terms
        max_keywords: Maximum number of keywords to return (None = unlimited)
    
    Returns:
        Cleaned keyword string
    
    Examples:
        >>> extract_keywords_advanced("How to implement OAuth2 authentication?")
        "implement OAuth2 authentication"
        
        >>> extract_keywords_advanced("Best practices for async/await in JavaScript", max_keywords=3)
        "practices async/await JavaScript"
    """
    if not text or not text.strip():
        return ""
    
    # Technical terms to always preserve (case-insensitive check)
    technical_terms = {
        'api', 'rest', 'oauth', 'jwt', 'sql', 'nosql', 'http', 'https',
        'json', 'xml', 'html', 'css', 'js', 'jsx', 'tsx', 'npm', 'yarn',
        'git', 'github', 'docker', 'kubernetes', 'aws', 'gcp', 'azure',
        'react', 'vue', 'angular', 'node', 'nodejs', 'python', 'java',
        'typescript', 'javascript', 'mongodb', 'postgresql', 'redis',
        'graphql', 'websocket', 'grpc', 'async', 'await', 'promise',
        'callback', 'webpack', 'babel', 'eslint', 'vite', 'nextjs',
        'ipc', 'electron', 'django', 'flask', 'fastapi', 'express',
        'middleware', 'cors', 'csrf', 'xss', 'ssl', 'tls', 'cdn',
        'ci', 'cd', 'devops', 'kubernetes', 'helm', 'terraform'
    }
    
    original_text = text
    text_lower = text.lower()
    
    # Extract technical terms first (preserve case)
    preserved_technical = []
    if keep_technical_terms:
        words_original = original_text.split()
        for i, word in enumerate(words_original):
            word_clean = re.sub(r'[^\w-]', '', word.lower())
            if word_clean in technical_terms:
                preserved_technical.append((i, word))  # Store position and original case
    
    # Standard keyword extraction
    text_lower = re.sub(r'[^\w\s-]', ' ', text_lower)
    words = text_lower.split()
    
    # Filter stopwords
    keywords = []
    for i, word in enumerate(words):
        # Check if this position has a technical term
        tech_word = next((tw[1] for tw in preserved_technical if tw[0] == i), None)
        if tech_word:
            keywords.append(tech_word)  # Use original case
        elif word not in STOPWORDS and len(word) >= min_word_length:
            keywords.append(word)
    
    # Limit keywords if specified
    if max_keywords and len(keywords) > max_keywords:
        keywords = keywords[:max_keywords]
    
    return ' '.join(keywords)



# Quick usage examples
if __name__ == "__main__":
    # Test cases
    test_queries = [
        "How do I create a React component?",
        "What is the best way to learn Python programming?",
        "Tell me about machine learning algorithms",
        "Can you explain how OAuth2 authentication works?",
        "I want to build a REST API with Node.js",
        "What are the differences between SQL and NoSQL databases?",
        "How to implement async/await in JavaScript?",
        "Show me the best practices for React hooks",
        "Explain IPC in Electron applications"
    ]
    
    print("=" * 60)
    print("KEYWORD EXTRACTION DEMO")
    print("=" * 60)
    
    for query in test_queries:
        keywords = extract_keywords_advanced(query)
        print(f"\n📝 Original: {query}")
        print(f"🎯 Keywords: {keywords}")
        print(f"📉 Reduction: {len(query.split())} → {len(keywords.split())} words")
    
    print("\n" + "=" * 60)