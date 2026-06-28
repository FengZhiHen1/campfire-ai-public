import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseCardDetailPage.css';

export default function CaseCardDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">干预卡片</span>
      </div>
      <PageContent>
        <div className="meta"><span>自伤行为</span><span>中度</span><span>公共场合</span><span>5-8岁</span></div>
        <div className="quartet">
          <h3>即时环境隔离与缓冲保护</h3>
          <div className="q-section immediate"><div className="q-head">即时安全干预动作</div><div className="q-body">1. 立即蹲下与孩子平视，用低沉平稳声音说出名字。{'\n'}2. 用外套或软物包裹孩子双手进行缓冲保护。{'\n'}3. 在2分钟内将孩子移至安静环境（母婴室/楼梯间）。{'\n'}4. 移除周围尖锐物品，保持至少1.5米安全距离。</div></div>
          <div className="q-section comforting"><div className="q-head">情绪安抚话术</div><div className="q-body">&ldquo;我在这里，你很难受对么？可以抓住我的手，用力抓没关系。&rdquo;——用第一人称，放慢语速至正常60%，每2-3秒说一个字。如孩子拒绝接触，安静陪伴即可。</div></div>
          <div className="q-section observation"><div className="q-head">后续观察指标</div><div className="q-body">• 尖叫是否在环境切换后3分钟内减弱{'\n'}• 自伤行为是否在5分钟内停止{'\n'}• 呼吸是否从急促转为平稳{'\n'}• 是否出现攻击转向行为</div></div>
          <div className="q-section medical"><div className="q-head">就医判断标准</div><div className="q-body">• 如10分钟后行为未减弱，联系值班专家{'\n'}• 如头部撞击导致明显外伤，前往急诊{'\n'}• 如出现意识模糊或呕吐，立即拨打120</div></div>
          <div className="q-note info">循证等级：中等（基于2个相似案例 + 1篇文献）</div>
        </div>
        <div className="footer-label"><span>证据等级</span><span style={{ fontWeight: 600 }}>基于真实案例 · 已审核</span></div>
      </PageContent>
    </>
  );
}
