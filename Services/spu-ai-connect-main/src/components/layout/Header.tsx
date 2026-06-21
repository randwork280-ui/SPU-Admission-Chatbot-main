import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Sun, Moon, Languages, Settings } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { Button } from '@/components/ui/button';
import spuLogo from '@/assets/spu-logo.png';

const Header = () => {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { language, toggleLanguage, isRTL } = useLanguage();

  return (
    <header className="sticky top-0 z-50 w-full glass border-b-2 border-primary/20 theme-transition">
      <div className="container flex h-20 items-center justify-between px-4 md:px-8">
        {/* Logo */}
        <Link 
          to="/" 
          className="flex items-center gap-3 transition-transform hover:scale-105"
        >
          <img 
            src={spuLogo} 
            alt={t('common.spu')} 
            className="h-20 md:h-24 w-auto object-contain"
          />
        </Link>

        {/* Center Motto */}
        <div className="hidden md:flex flex-col items-center">
          <p className="text-sm md:text-lg font-semibold text-primary text-center leading-tight">
            {t('common.motto')}
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Admin Link */}
          <Button
            variant="ghost"
            size="icon"
            asChild
            className="rounded-xl hover:bg-accent hover:text-accent-foreground transition-all duration-300"
            title={t('nav.admin')}
          >
            <Link to="/admin">
              <Settings className="h-5 w-5" />
            </Link>
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="relative overflow-hidden rounded-xl hover:bg-accent hover:text-accent-foreground transition-all duration-300"
            title={t('header.toggleTheme')}
          >
            <Sun className={`h-5 w-5 transition-all duration-300 ${theme === 'dark' ? 'rotate-90 scale-0' : 'rotate-0 scale-100'}`} />
            <Moon className={`absolute h-5 w-5 transition-all duration-300 ${theme === 'dark' ? 'rotate-0 scale-100' : '-rotate-90 scale-0'}`} />
          </Button>

          {/* Language Toggle */}
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleLanguage}
            className="flex items-center gap-2 rounded-xl px-3 hover:bg-accent hover:text-accent-foreground transition-all duration-300 font-semibold"
            title={t('header.toggleLanguage')}
          >
            <Languages className="h-4 w-4" />
            <span className="text-sm">{language === 'ar' ? 'EN' : 'عربي'}</span>
          </Button>
        </div>
      </div>

      {/* Mobile Motto */}
      <div className="md:hidden px-4 pb-3">
        <p className="text-xs font-medium text-primary text-center">
          {t('common.motto')}
        </p>
      </div>
    </header>
  );
};

export default Header;
