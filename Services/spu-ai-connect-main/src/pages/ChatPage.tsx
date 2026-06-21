import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  Copy,
  DollarSign,
  FileText,
  GraduationCap,
  Phone,
  Scale,
  Send,
  Trash2,
  User,
} from 'lucide-react';
import spuLogo from '@/assets/spu-logo.png';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { useLanguage } from '@/contexts/LanguageContext';
import { toast } from 'sonner';
import { chatStreamUrl } from '@/lib/api';

interface Source {
  content: string;
  score: number;
  chunk_id?: string;
  metadata?: {
    faculty?: string;
    doc_category?: string;
    source?: string;
    page?: string | number;
    page_number?: string | number;
    header_path?: string;
    official_date?: string;
  };
}

interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: Date;
  sources?: Source[];
}

interface QuickAction {
  key: string;
  icon: React.ReactNode;
  query: string;
}

interface StreamMetadata {
  conversationId: string;
  sources: Source[];
  confidence: number;
  language: string;
}

async function sendMessageStream(
  query: string,
  conversationId: string | undefined,
  onToken: (token: string) => void,
  onMetadata: (metadata: StreamMetadata) => void,
  onError: (error: string) => void
) {
  const response = await fetch(chatStreamUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      k: 8,
      min_relevance_score: 0.3,
      conversation_id: conversationId || undefined,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';

    for (const event of events) {
      const dataLine = event.split('\n').find((line) => line.startsWith('data: '));
      if (!dataLine) continue;

      try {
        const data = JSON.parse(dataLine.slice(6));
        if (data.type === 'token') {
          onToken(data.content || '');
        } else if (data.type === 'metadata') {
          onMetadata({
            conversationId: data.conversation_id,
            sources: data.sources || [],
            confidence: data.confidence || 0,
            language: data.language || 'english',
          });
        } else if (data.type === 'error') {
          onError(data.content || 'Unknown error');
        }
      } catch {
        // Ignore malformed SSE events.
      }
    }
  }
}

const ChatPage = () => {
  const { t } = useTranslation();
  const { isRTL } = useLanguage();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const quickActions: QuickAction[] = [
    { key: 'faculties', icon: <GraduationCap className="h-5 w-5" />, query: isRTL ? 'ما هي الكليات المتاحة في الجامعة السورية الخاصة؟' : 'What faculties are available at SPU?' },
    { key: 'fees', icon: <DollarSign className="h-5 w-5" />, query: isRTL ? 'ما هي الرسوم الدراسية؟' : 'What are the tuition fees?' },
    { key: 'admission', icon: <ClipboardCheck className="h-5 w-5" />, query: isRTL ? 'ما هي شروط القبول في الجامعة؟' : 'What are the admission requirements?' },
    { key: 'programs', icon: <BookOpen className="h-5 w-5" />, query: isRTL ? 'ما هي البرامج والتخصصات المتاحة؟' : 'What programs and majors are available?' },
    { key: 'contact', icon: <Phone className="h-5 w-5" />, query: isRTL ? 'كيف يمكنني التواصل مع الجامعة؟' : 'How can I contact the university?' },
    { key: 'rules', icon: <Scale className="h-5 w-5" />, query: isRTL ? 'ما هي القواعد والقرارات في الجامعة؟' : 'What are the university rules and regulations?' },
  ];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  }, [input]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userQuery = input.trim();
    const userMessage: Message = {
      id: Date.now().toString(),
      content: userQuery,
      role: 'user',
      timestamp: new Date(),
    };
    const assistantId = (Date.now() + 1).toString();

    setMessages((previous) => [
      ...previous,
      userMessage,
      { id: assistantId, content: '', role: 'assistant', timestamp: new Date() },
    ]);
    setInput('');
    setIsLoading(true);

    let streamedContent = '';
    try {
      await sendMessageStream(
        userQuery,
        conversationId,
        (token) => {
          streamedContent += token;
          setMessages((previous) =>
            previous.map((message) =>
              message.id === assistantId ? { ...message, content: streamedContent } : message
            )
          );
        },
        (metadata) => {
          if (metadata.conversationId) {
            setConversationId(metadata.conversationId);
          }
          setMessages((previous) =>
            previous.map((message) =>
              message.id === assistantId ? { ...message, sources: metadata.sources } : message
            )
          );
        },
        (error) => {
          setMessages((previous) =>
            previous.map((message) =>
              message.id === assistantId ? { ...message, content: `Error: ${error}` } : message
            )
          );
        }
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : t('chat.errorMessage');
      setMessages((previous) =>
        previous.map((item) =>
          item.id === assistantId ? { ...item, content: `Error: ${message}` } : item
        )
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handleCopy = async (content: string, id: string) => {
    await navigator.clipboard.writeText(content);
    setCopiedId(id);
    toast.success(t('chat.copied'));
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleClearChat = () => {
    setMessages([]);
    setConversationId(undefined);
    setExpandedSources(new Set());
    toast.success(isRTL ? 'تم مسح المحادثة' : 'Chat cleared');
  };

  const toggleSources = (messageId: string) => {
    setExpandedSources((previous) => {
      const next = new Set(previous);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] animate-fade-in">
      {!hasMessages && (
        <div className="flex-1 flex flex-col items-center justify-center px-4 py-8">
          <div className="text-center mb-8 animate-fade-in">
            <h1 className="text-2xl md:text-4xl font-bold text-primary mb-4">
              {t('chat.welcome')}
            </h1>
            <p className="text-lg text-muted-foreground max-w-xl mx-auto">
              {t('chat.subtitle')}
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4 max-w-2xl w-full">
            {quickActions.map((action, index) => (
              <button
                key={action.key}
                onClick={() => {
                  setInput(action.query);
                  textareaRef.current?.focus();
                }}
                className={cn(
                  "flex flex-col items-center gap-2 p-4 rounded-xl",
                  "bg-card border-2 border-border hover:border-primary",
                  "transition-all duration-300 hover:shadow-lg hover:scale-[1.02]",
                  "group animate-fade-in"
                )}
                style={{ animationDelay: `${index * 100}ms` }}
              >
                <div className="p-3 rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                  {action.icon}
                </div>
                <span className="text-sm font-medium text-center text-foreground">
                  {t(`chat.quickActions.${action.key}`)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {hasMessages && (
        <div className="flex-1 overflow-y-auto space-y-4 pb-4 px-2 md:px-4">
          {messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                'flex gap-3 animate-fade-in',
                message.role === 'user'
                  ? (isRTL ? 'flex-row' : 'flex-row-reverse')
                  : (isRTL ? 'flex-row-reverse' : 'flex-row')
              )}
            >
              <div
                className={cn(
                  'flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium overflow-hidden',
                  message.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                )}
              >
                {message.role === 'user' ? (
                  <User className="h-5 w-5" />
                ) : (
                  <img src={spuLogo} alt="SPU" className="h-8 w-8 object-contain" />
                )}
              </div>

              <div className="max-w-[70%] md:max-w-[75%] group">
                <div
                  className={cn(
                    'px-4 py-3 relative',
                    message.role === 'user'
                      ? cn(
                        'bg-primary text-primary-foreground',
                        isRTL
                          ? 'rounded-tl-2xl rounded-tr-sm rounded-br-2xl rounded-bl-2xl'
                          : 'rounded-tr-2xl rounded-tl-sm rounded-bl-2xl rounded-br-2xl'
                      )
                      : cn(
                        'bg-muted text-foreground',
                        isRTL
                          ? 'rounded-tr-2xl rounded-tl-sm rounded-bl-2xl rounded-br-2xl'
                          : 'rounded-tl-2xl rounded-tr-sm rounded-br-2xl rounded-bl-2xl'
                      )
                  )}
                >
                  {message.role === 'assistant' ? (
                    <div className="prose prose-sm dark:prose-invert max-w-none prose-p:leading-loose prose-p:mb-6 prose-li:mb-2">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="leading-relaxed whitespace-pre-wrap">{message.content}</p>
                  )}
                </div>

                <div className={cn(
                  "flex items-center gap-2 mt-1",
                  message.role === 'user'
                    ? (isRTL ? 'justify-start' : 'justify-end')
                    : (isRTL ? 'justify-end' : 'justify-start')
                )}>
                  {message.role === 'assistant' && (
                    <button
                      onClick={() => handleCopy(message.content, message.id)}
                      className={cn(
                        "opacity-0 group-hover:opacity-100 transition-opacity",
                        "p-1 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
                      )}
                      title={t('chat.copy')}
                    >
                      {copiedId === message.id ? (
                        <Check className="h-3.5 w-3.5 text-green-500" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </button>
                  )}

                  {message.role === 'assistant' && message.sources && message.sources.length > 0 && (
                    <button
                      onClick={() => toggleSources(message.id)}
                      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                    >
                      <FileText className="h-3 w-3" />
                      <span>{isRTL ? `عرض المصادر (${message.sources.length})` : `View Sources (${message.sources.length})`}</span>
                      {expandedSources.has(message.id) ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </button>
                  )}

                  <span className="text-xs text-muted-foreground">
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>

                {message.role === 'assistant' && message.sources && expandedSources.has(message.id) && (
                  <div className="mt-3 space-y-2 animate-fade-in">
                    <div className="text-xs font-medium text-muted-foreground mb-2">
                      {isRTL ? 'المصادر المستخدمة:' : 'Sources Used:'}
                    </div>
                    {message.sources.map((source, idx) => {
                      const metadata = source.metadata || {};
                      const page = metadata.page || metadata.page_number;
                      return (
                        <div key={`${message.id}-${idx}`} className="p-3 rounded-lg border border-border bg-background/50 text-sm">
                          <div className="flex items-center justify-between gap-3 mb-2">
                            <span className="font-medium text-primary">
                              {isRTL ? `المصدر ${idx + 1}` : `Source ${idx + 1}`}
                            </span>
                            <span className={cn(
                              "text-xs px-2 py-0.5 rounded-full",
                              source.score >= 0.7 ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
                                source.score >= 0.4 ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" :
                                  "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                            )}>
                              {(source.score * 100).toFixed(0)}% {isRTL ? 'تطابق' : 'match'}
                            </span>
                          </div>

                          <div className="flex gap-2 mb-2 flex-wrap">
                            {metadata.source && <span className="text-xs px-2 py-0.5 rounded bg-muted">{metadata.source}</span>}
                            {metadata.faculty && <span className="text-xs px-2 py-0.5 rounded bg-muted">{metadata.faculty}</span>}
                            {metadata.doc_category && <span className="text-xs px-2 py-0.5 rounded bg-muted">{metadata.doc_category}</span>}
                            {page && <span className="text-xs px-2 py-0.5 rounded bg-muted">{isRTL ? `صفحة ${page}` : `Page ${page}`}</span>}
                          </div>

                          {metadata.header_path && (
                            <p className="text-xs text-muted-foreground mb-2">{metadata.header_path}</p>
                          )}
                          <p className={cn("text-muted-foreground text-xs leading-relaxed", isRTL && "text-right")}>
                            {source.content.length > 300 ? `${source.content.substring(0, 300)}...` : source.content}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className={cn('flex gap-3', isRTL ? 'flex-row-reverse' : 'flex-row')}>
              <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center overflow-hidden">
                <img src={spuLogo} alt="SPU" className="h-8 w-8 object-contain" />
              </div>
              <div className="bg-muted px-4 py-3 rounded-2xl">
                <div className="flex gap-1.5">
                  <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      <div className="mt-auto border-t border-border bg-background/80 backdrop-blur-sm p-4 shadow-[0_-4px_20px_-5px_rgba(0,0,0,0.1)]">
        <div className="flex items-end gap-3 max-w-4xl mx-auto">
          {hasMessages && (
            <Button
              variant="ghost"
              size="icon"
              onClick={handleClearChat}
              className="shrink-0 text-muted-foreground hover:text-destructive"
              title={t('chat.clearChat')}
            >
              <Trash2 className="h-5 w-5" />
            </Button>
          )}

          <div className="flex-1 relative">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyPress}
              placeholder={t('chat.placeholder')}
              className={cn(
                "min-h-[48px] max-h-[150px] resize-none rounded-xl border-2",
                "border-border focus:border-primary transition-colors",
                "pr-4 pl-4 py-3",
                isRTL && "text-right"
              )}
              disabled={isLoading}
              rows={1}
            />
            {input.length > 100 && (
              <span className={cn("absolute bottom-1 text-xs text-muted-foreground", isRTL ? 'left-3' : 'right-3')}>
                {input.length}
              </span>
            )}
          </div>

          <Button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="shrink-0 h-12 px-5 rounded-xl bg-primary hover:bg-primary/90 transition-all duration-300 shadow-soft hover:shadow-glow"
          >
            <Send className={cn("h-5 w-5", isRTL && "rotate-180")} />
            <span className="sr-only">{t('chat.send')}</span>
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
