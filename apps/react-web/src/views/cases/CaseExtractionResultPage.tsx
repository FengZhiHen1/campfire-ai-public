import { useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';

export default function CaseExtractionResultPage() {
  const { id } = useParams<{ id: string }>();
  return <PageContent><p>AI 提取结果 {id}</p></PageContent>;
}
