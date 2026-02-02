import { useState, useEffect } from 'react';
import { Search, Globe, ArrowRight, ExternalLink, Loader2 } from 'lucide-react';
import type { ControllerProps, ExpansionProps, WebSearchData, SearchResult } from '../types';

// Panel component (search input)
export function WebSearch({ isActive, setExpansionVisible, setExpansionData }: ControllerProps) {
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSearch = () => {
    if (!query.trim()) return;
    
    setIsLoading(true);
    setExpansionVisible(true);
    
    // Simulate search - replace with actual API call
    setTimeout(() => {
      const mockData: WebSearchData = {
        query,
        summary: `Here's what I found about "${query}". This is a brief AI-generated summary of the top results...`,
        results: [
          { title: `${query} - Wikipedia`, url: 'https://wikipedia.org', favicon: '📚', snippet: 'Comprehensive overview...' },
          { title: `Understanding ${query}`, url: 'https://example.com', favicon: '📖', snippet: 'In-depth guide...' },
          { title: `${query} Tutorial`, url: 'https://tutorial.dev', favicon: '💡', snippet: 'Step by step...' },
          { title: `${query} Documentation`, url: 'https://docs.dev', favicon: '📄', snippet: 'Official docs...' },
        ],
        isLoading: false,
      };
      setExpansionData(mockData);
      setIsLoading(false);
    }, 800);
  };

  if (!isActive) return null;

  return (
    <div className="flex items-center justify-center px-4 w-full">
      <div className="flex items-center gap-2 w-full max-w-[280px]">
        <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg
                        bg-indigo-300/10 border border-indigo-300/15">
          <Search className="w-3.5 h-3.5 text-indigo-200/60" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search the web..."
            className="flex-1 bg-transparent border-none outline-none
                       text-xs text-indigo-100 placeholder:text-indigo-200/40"
          />
          {isLoading && <Loader2 className="w-3.5 h-3.5 text-indigo-300 animate-spin" />}
        </div>
      </div>
    </div>
  );
}

// Expansion component (search results)
export function WebSearchExpansion({ isExpanded, data }: ExpansionProps) {
  if (!isExpanded || !data) return null;

  const searchData = data as WebSearchData;

  return (
    <div className="flex flex-col gap-4">
      {/* Summary Card */}
      {searchData.summary && (
        <div
          className="p-3 rounded-xl bg-linear-to-br from-indigo-500/20 to-purple-500/10
                        border border-indigo-300/15"
        >
          <p className="text-xs text-indigo-100/90 leading-relaxed">
            {searchData.summary}
          </p>
        </div>
      )}

      {/* Results List */}
      <div className="flex flex-col gap-2">
        {searchData.results.map((result, index) => (
          <a
            key={index}
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-3 p-3 rounded-xl
                       bg-indigo-300/5 hover:bg-indigo-300/10
                       border border-transparent hover:border-indigo-300/15
                       transition-all duration-200 group"
          >
            <span className="text-lg">{result.favicon || "🔗"}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm text-indigo-100 font-medium truncate">
                  {result.title}
                </span>
                <ExternalLink className="w-3 h-3 text-indigo-300/50 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              {result.snippet && (
                <p className="text-[10px] text-indigo-200/50 mt-0.5 line-clamp-1">
                  {result.snippet}
                </p>
              )}
              <span className="text-[10px] text-indigo-300/40 truncate">
                {result.url}
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

// Plugin config
export const webSearchPlugin = {
  id: 'web-search',
  name: 'Search',
  icon: <Globe className="w-4 h-4" />,
  component: WebSearch,
  expansionComponent: WebSearchExpansion,
  order: 4,
};
