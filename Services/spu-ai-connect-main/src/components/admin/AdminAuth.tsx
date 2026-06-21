import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Lock, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import {
  adminLogin,
  checkAdminAuth as checkStoredAdminAuth,
  logoutAdmin as clearAdminAuth,
} from '@/lib/api';

interface AdminAuthProps {
  children: React.ReactNode;
}

export const checkAdminAuth = (): boolean => checkStoredAdminAuth();

export const logoutAdmin = () => {
  clearAdminAuth();
};

const AdminAuth = ({ children }: AdminAuthProps) => {
  const { t } = useTranslation();
  const [isAuthenticated, setIsAuthenticated] = useState(checkAdminAuth());
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isShaking, setIsShaking] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      await adminLogin(password);
      setIsAuthenticated(true);
      setPassword('');
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : t('admin.auth.error'));
      setIsShaking(true);
      setTimeout(() => setIsShaking(false), 500);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-[calc(100vh-12rem)] flex items-center justify-center p-4">
      <Card className={cn(
        "w-full max-w-md glass-card animate-fade-in",
        isShaking && "animate-shake"
      )}>
        <CardHeader className="text-center">
          <div className="mx-auto w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
            <Lock className="h-8 w-8 text-primary" />
          </div>
          <CardTitle className="text-2xl">{t('admin.auth.title')}</CardTitle>
          <CardDescription>{t('admin.auth.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <Input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                placeholder={t('admin.auth.password')}
                className={cn(
                  "h-12 pr-12",
                  error && "border-destructive focus:border-destructive"
                )}
                autoFocus
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </div>

            {error && (
              <p className="text-sm text-destructive animate-fade-in">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full h-12 bg-primary hover:bg-primary/90"
              disabled={!password.trim() || isSubmitting}
            >
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : t('admin.auth.submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default AdminAuth;
