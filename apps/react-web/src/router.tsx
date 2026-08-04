import { createBrowserRouter } from 'react-router-dom';
import AppShell from '@/views/_shared/layout/AppShell';
import AuthGuardLayout from '@/view/layouts/AuthGuardLayout';
import LoginPage from '@/view/pages/auth/LoginPage';
import RegisterPage from '@/view/pages/auth/RegisterPage';
import ReviewStatusPage from '@/view/pages/auth/ReviewStatusPage';
import NoAccessPage from '@/view/pages/auth/NoAccessPage';
import InviteCodesPage from '@/view/pages/admin/InviteCodesPage';
import ReviewsPage from '@/view/pages/admin/ReviewsPage';
import HomePage from '@/views/home/HomePage';
import ConsultIndexPage from '@/views/consult/ConsultIndexPage';
import ConsultSessionPage from '@/views/consult/ConsultSessionPage';
import ConsultHistoryPage from '@/views/consult/ConsultHistoryPage';
import ProfileListPage from '@/views/profiles/ProfileListPage';
import ProfileEditPage from '@/views/profiles/ProfileEditPage';
import CaseListPage from '@/views/cases/CaseListPage';
import CaseDetailPage from '@/views/cases/CaseDetailPage';
import CaseReviewPage from '@/views/cases/CaseReviewPage';
import CaseCardDetailPage from '@/views/cases/CaseCardDetailPage';
import CaseExtractionResultPage from '@/views/cases/CaseExtractionResultPage';
import CaseNarrativeSubmitPage from '@/views/cases/CaseNarrativeSubmitPage';
import TicketDetailPage from '@/views/tickets/TicketDetailPage';

/**
 * 路由注册（ADR-013）：
 * - /login、/register 公开
 * - 其余全部包裹 AuthGuardLayout（未登录跳登录、pending/rejected 仅见状态页、
 *   /admin 仅 admin、maintainer 仅见 no-access）
 * - 业务页面 S6 五层重组前维持 views/logics 旧结构
 */
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: <AuthGuardLayout />,
    children: [
      { path: '/review-status', element: <ReviewStatusPage /> },
      { path: '/no-access', element: <NoAccessPage /> },
      { path: '/admin/invite-codes', element: <InviteCodesPage /> },
      { path: '/admin/reviews', element: <ReviewsPage /> },
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'consult', element: <ConsultIndexPage /> },
          { path: 'consult/session/:sessionId', element: <ConsultSessionPage /> },
          { path: 'consult/history', element: <ConsultHistoryPage /> },
          { path: 'profiles', element: <ProfileListPage /> },
          { path: 'profiles/edit/:id?', element: <ProfileEditPage /> },
          { path: 'cases', element: <CaseListPage /> },
          { path: 'cases/:id', element: <CaseDetailPage /> },
          { path: 'cases/review', element: <CaseReviewPage /> },
          { path: 'cases/card/:id', element: <CaseCardDetailPage /> },
          { path: 'cases/extraction/:id', element: <CaseExtractionResultPage /> },
          { path: 'cases/narrative', element: <CaseNarrativeSubmitPage /> },
          { path: 'tickets/:id', element: <TicketDetailPage /> },
        ],
      },
    ],
  },
]);
