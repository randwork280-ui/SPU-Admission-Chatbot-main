import { Outlet } from 'react-router-dom';
import Header from './Header';

const MainLayout = () => {
  return (
    <div className="min-h-screen flex flex-col bg-background theme-transition gradient-overlay">
      <Header />
      <main className="flex-1 container px-4 py-6 md:py-8">
        <Outlet />
      </main>
    </div>
  );
};

export default MainLayout;
