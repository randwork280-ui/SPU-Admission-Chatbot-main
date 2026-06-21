import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Circle,
  Clock,
  Database,
  Eraser,
  FileText,
  FolderSearch,
  LayoutDashboard,
  Loader2,
  LogOut,
  MessageSquareText,
  Play,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import AdminAuth, { logoutAdmin } from '@/components/admin/AdminAuth';
import { fetchAdminStats, runAutoPipeline, scanDataFiles, sendChatMessage } from '@/lib/api';

type PipelineStatus = 'idle' | 'running' | 'success' | 'error';

interface Stats {
  totalDocuments: number;
  totalChunks: number;
  vectorDbDocs: number;
  lastUpdate: string;
  avgChunkSize: number;
}

interface ScannedFile {
  name: string;
  size_bytes: number;
  type: string;
  metadata?: Record<string, unknown>;
}

const emptyStats: Stats = {
  totalDocuments: 0,
  totalChunks: 0,
  vectorDbDocs: 0,
  lastUpdate: '-',
  avgChunkSize: 0,
};

const AdminPage = () => {
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>('idle');
  const [pipelineStage, setPipelineStage] = useState(0);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [scannedFiles, setScannedFiles] = useState<ScannedFile[]>([]);
  const [testQueryModalOpen, setTestQueryModalOpen] = useState(false);
  const [testQuery, setTestQuery] = useState('');
  const [testResponse, setTestResponse] = useState('');
  const [isTestLoading, setIsTestLoading] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const data = await fetchAdminStats();
      setStats({
        totalDocuments: data.total_documents || 0,
        totalChunks: data.total_chunks || 0,
        vectorDbDocs: data.vector_db_docs || 0,
        lastUpdate: data.last_update || '-',
        avgChunkSize: data.avg_chunk_size || 0,
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('chat.errorMessage'));
    }
  }, [t]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const runPipeline = async () => {
    setPipelineStatus('running');
    setPipelineError(null);
    setPipelineStage(1);

    try {
      const data = await runAutoPipeline();
      if (!data.success) {
        throw new Error(data.error || data.message || t('admin.pipeline.status.failed'));
      }
      setPipelineStage(4);
      setPipelineStatus('success');
      toast.success(t('admin.pipeline.status.success'));
      fetchStats();
    } catch (error) {
      const message = error instanceof Error ? error.message : t('admin.pipeline.status.failed');
      setPipelineStatus('error');
      setPipelineError(message);
      toast.error(message);
    }
  };

  const scanFiles = async () => {
    try {
      const data = await scanDataFiles();
      setScannedFiles(data.files || []);
      setScanModalOpen(true);
      toast.info(`${t('admin.quickActions.scanData')}: ${data.total_files || 0}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('chat.errorMessage'));
    }
  };

  const testQuerySubmit = async () => {
    if (!testQuery.trim()) return;
    setIsTestLoading(true);
    setTestResponse('');

    try {
      const data = await sendChatMessage(testQuery, undefined, 5);
      setTestResponse(data.answer || 'No response');
    } catch (error) {
      setTestResponse(error instanceof Error ? error.message : t('chat.errorMessage'));
    } finally {
      setIsTestLoading(false);
    }
  };

  const clearCache = () => {
    sessionStorage.removeItem('conversation_id');
    toast.success(isRTL ? 'تم تنظيف الذاكرة المحلية' : 'Local cache cleared');
  };

  const handleLogout = () => {
    logoutAdmin();
    window.location.reload();
  };

  const pipelineStages = [
    { key: 'loading', label: t('admin.pipeline.stages.loading') },
    { key: 'splitting', label: t('admin.pipeline.stages.splitting') },
    { key: 'embedding', label: t('admin.pipeline.stages.embedding') },
    { key: 'storing', label: t('admin.pipeline.stages.storing') },
  ];

  const statusIcon = {
    idle: <Circle className="h-4 w-4 text-muted-foreground" />,
    running: <Loader2 className="h-4 w-4 text-primary animate-spin" />,
    success: <CheckCircle2 className="h-4 w-4 text-green-500" />,
    error: <XCircle className="h-4 w-4 text-destructive" />,
  }[pipelineStatus];

  const statusText = {
    idle: t('admin.pipeline.status.ready'),
    running: t('admin.pipeline.status.running'),
    success: t('admin.pipeline.status.success'),
    error: t('admin.pipeline.status.failed'),
  }[pipelineStatus];

  const statItems = [
    { label: t('admin.stats.totalDocuments'), value: stats.totalDocuments, icon: <FileText className="h-5 w-5 text-blue-500 mb-2" /> },
    { label: t('admin.stats.totalChunks'), value: stats.totalChunks, icon: <LayoutDashboard className="h-5 w-5 text-purple-500 mb-2" /> },
    { label: t('admin.stats.vectorDbDocs'), value: stats.vectorDbDocs, icon: <Database className="h-5 w-5 text-green-500 mb-2" /> },
    { label: t('admin.stats.avgChunkSize'), value: stats.avgChunkSize, icon: <CheckCircle2 className="h-5 w-5 text-orange-500 mb-2" /> },
    { label: t('admin.stats.lastUpdate'), value: stats.lastUpdate, icon: <Clock className="h-5 w-5 text-gray-500 mb-2" /> },
  ];

  return (
    <AdminAuth>
      <div className="min-h-screen bg-background pb-8">
        <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur-md">
          <div className="container mx-auto px-4 h-16 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <LayoutDashboard className="h-6 w-6 text-primary" />
              <h1 className="text-xl font-bold text-primary">{t('admin.title')}</h1>
            </div>
            <div className="flex items-center gap-4">
              <Button variant="ghost" size="icon" asChild>
                <Link to="/">
                  <ArrowRight className={cn("h-5 w-5", isRTL && "rotate-180")} />
                </Link>
              </Button>
              <Button variant="outline" size="sm" onClick={handleLogout} className="gap-2">
                <LogOut className="h-4 w-4" />
                <span className="hidden sm:inline">{t('admin.auth.logout')}</span>
              </Button>
            </div>
          </div>
        </header>

        <main className="container mx-auto px-4 py-8 space-y-8">
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Play className="h-5 w-5 text-primary" />
                {t('admin.pipeline.title')}
              </CardTitle>
              <CardDescription>{t('admin.pipeline.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                <Button
                  onClick={runPipeline}
                  disabled={pipelineStatus === 'running'}
                  className="gap-2 bg-primary hover:bg-primary/90"
                  size="lg"
                >
                  {pipelineStatus === 'running' ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Play className="h-5 w-5" />
                  )}
                  {t('admin.pipeline.runButton')}
                </Button>
                <div className="flex items-center gap-2">
                  {statusIcon}
                  <span className={cn(
                    "text-sm font-medium",
                    pipelineStatus === 'success' && "text-green-500",
                    pipelineStatus === 'error' && "text-destructive"
                  )}>
                    {statusText}
                  </span>
                  {pipelineError && <span className="text-sm text-destructive">: {pipelineError}</span>}
                </div>
              </div>

              <div className="space-y-3">
                <Progress value={(pipelineStage / 4) * 100} className="h-2" />
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {pipelineStages.map((stage, index) => (
                    <div
                      key={stage.key}
                      className={cn(
                        "flex items-center gap-2 p-2 rounded-lg text-sm transition-colors",
                        index < pipelineStage ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
                      )}
                    >
                      {index < pipelineStage ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
                      <span className="truncate">{stage.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="glass-card shadow-lg border-primary/20">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-2xl">
                  <BarChart3 className="h-6 w-6 text-primary" />
                  {t('admin.stats.title')}
                </CardTitle>
                <Button variant="ghost" size="icon" onClick={fetchStats}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                {statItems.map((stat) => (
                  <div key={stat.label} className="flex flex-col items-center justify-center p-4 rounded-xl bg-muted/30 border border-border/50">
                    {stat.icon}
                    <span className="text-muted-foreground text-xs text-center mb-1">{stat.label}</span>
                    <span className="font-bold text-xl text-foreground text-center">{stat.value}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5 text-primary" />
                {t('admin.quickActions.title')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Button variant="outline" className="h-auto py-6 flex-col gap-3" onClick={scanFiles}>
                  <FolderSearch className="h-6 w-6 text-blue-500" />
                  <span className="font-medium">{t('admin.quickActions.scanData')}</span>
                </Button>
                <Button
                  variant="outline"
                  className="h-auto py-6 flex-col gap-3"
                  onClick={() => {
                    setTestQuery('');
                    setTestResponse('');
                    setTestQueryModalOpen(true);
                  }}
                >
                  <MessageSquareText className="h-6 w-6 text-purple-500" />
                  <span className="font-medium">{t('admin.quickActions.testQuery')}</span>
                </Button>
                <Button variant="outline" className="h-auto py-6 flex-col gap-3" onClick={clearCache}>
                  <Eraser className="h-6 w-6 text-red-500" />
                  <span className="font-medium">{t('admin.quickActions.clearCache')}</span>
                </Button>
              </div>
            </CardContent>
          </Card>
        </main>

        <Dialog open={scanModalOpen} onOpenChange={setScanModalOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>{t('admin.modals.scanData.title')}</DialogTitle>
              <DialogDescription>
                {t('admin.modals.scanData.totalFiles')}: {scannedFiles.length}
              </DialogDescription>
            </DialogHeader>
            <ScrollArea className="max-h-[300px]">
              {scannedFiles.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">
                  {t('admin.modals.scanData.noFiles')}
                </p>
              ) : (
                <div className="space-y-2">
                  {scannedFiles.map((file) => (
                    <div key={file.name} className="flex items-center gap-3 p-2 rounded-lg bg-muted">
                      <FileText className="h-4 w-4 text-primary shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{file.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {((file.size_bytes || 0) / 1024).toFixed(1)} KB - {file.type}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </ScrollArea>
          </DialogContent>
        </Dialog>

        <Dialog open={testQueryModalOpen} onOpenChange={setTestQueryModalOpen}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>{t('admin.modals.testQuery.title')}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="flex gap-2">
                <Input
                  value={testQuery}
                  onChange={(event) => setTestQuery(event.target.value)}
                  placeholder={t('admin.modals.testQuery.placeholder')}
                  className={cn(isRTL && "text-right")}
                  onKeyDown={(event) => event.key === 'Enter' && testQuerySubmit()}
                />
                <Button onClick={testQuerySubmit} disabled={isTestLoading || !testQuery.trim()}>
                  {isTestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : t('admin.modals.testQuery.test')}
                </Button>
              </div>
              {testResponse && (
                <div className="p-4 rounded-lg bg-muted">
                  <p className="text-sm font-medium mb-2">{t('admin.modals.testQuery.response')}:</p>
                  <p className="text-sm text-muted-foreground whitespace-pre-wrap">{testResponse}</p>
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </AdminAuth>
  );
};

export default AdminPage;
