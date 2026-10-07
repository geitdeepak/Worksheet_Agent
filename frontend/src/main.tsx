import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import './styles/tokens.css';
import './styles/palette.css';
import './styles/bundle.css';
import './styles/app.css';
import { AuthProvider, ClassesProvider, ToastProvider, useAuth } from './app';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Classes from './pages/Classes';
import ClassWorkspace from './pages/ClassWorkspace';
import ReviewList from './pages/ReviewList';
import WorksheetReview from './pages/WorksheetReview';
import DeliveryList from './pages/DeliveryList';
import DeliveryMonitor from './pages/DeliveryMonitor';
import History from './pages/History';
import Settings from './pages/Settings';
import ParentHome from './pages/ParentHome';

/** Staff pages (admins and teachers). Parents only have their practice-sheet page. */
function Protected({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (user.role === 'parent') return <Navigate to="/parent" replace />;
  return <ClassesProvider>{children}</ClassesProvider>;
}

function ParentOnly({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" state={{ from: '/parent' }} replace />;
  if (user.role !== 'parent') return <Navigate to="/" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/classes" element={<Protected><Classes /></Protected>} />
      <Route path="/classes/:id" element={<Protected><ClassWorkspace /></Protected>} />
      <Route path="/classes/:id/:tab" element={<Protected><ClassWorkspace /></Protected>} />
      <Route path="/review" element={<Protected><ReviewList /></Protected>} />
      <Route path="/review/:id" element={<Protected><WorksheetReview /></Protected>} />
      <Route path="/delivery" element={<Protected><DeliveryList /></Protected>} />
      <Route path="/delivery/:id" element={<Protected><DeliveryMonitor /></Protected>} />
      <Route path="/history" element={<Protected><History /></Protected>} />
      <Route path="/settings" element={<Protected><Settings /></Protected>} />
      <Route path="/parent" element={<ParentOnly><ParentHome /></ParentOnly>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);
