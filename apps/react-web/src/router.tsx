import { createBrowserRouter } from 'react-router-dom';
import AppShell from '@/views/_shared/layout/AppShell';
import HomePage from '@/views/home/HomePage';
import ConsultIndexPage from '@/views/consult/ConsultIndexPage';
import ConsultSelectPage from '@/views/consult/ConsultSelectPage';
import ConsultDetailPage from '@/views/consult/ConsultDetailPage';
import ConsultHistoryPage from '@/views/consult/ConsultHistoryPage';
import ProfileListPage from '@/views/profiles/ProfileListPage';
import ProfileEditPage from '@/views/profiles/ProfileEditPage';
import CaseListPage from '@/views/cases/CaseListPage';
import CaseDetailPage from '@/views/cases/CaseDetailPage';
import CaseSubmitPage from '@/views/cases/CaseSubmitPage';
import CaseReviewPage from '@/views/cases/CaseReviewPage';
import CaseCardDetailPage from '@/views/cases/CaseCardDetailPage';
import CaseExtractionResultPage from '@/views/cases/CaseExtractionResultPage';
import CaseNarrativeSubmitPage from '@/views/cases/CaseNarrativeSubmitPage';
import TicketDetailPage from '@/views/tickets/TicketDetailPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'consult', element: <ConsultIndexPage /> },
      { path: 'consult/select', element: <ConsultSelectPage /> },
      { path: 'consult/:id', element: <ConsultDetailPage /> },
      { path: 'consult/history', element: <ConsultHistoryPage /> },
      { path: 'profiles', element: <ProfileListPage /> },
      { path: 'profiles/edit/:id?', element: <ProfileEditPage /> },
      { path: 'cases', element: <CaseListPage /> },
      { path: 'cases/:id', element: <CaseDetailPage /> },
      { path: 'cases/submit', element: <CaseSubmitPage /> },
      { path: 'cases/review', element: <CaseReviewPage /> },
      { path: 'cases/card/:id', element: <CaseCardDetailPage /> },
      { path: 'cases/extraction/:id', element: <CaseExtractionResultPage /> },
      { path: 'cases/narrative', element: <CaseNarrativeSubmitPage /> },
      { path: 'tickets/:id', element: <TicketDetailPage /> },
    ],
  },
]);
