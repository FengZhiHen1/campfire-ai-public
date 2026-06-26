/**
 * 单例内存数据库 —— 维护所有域 in-memory 集合。
 * mockRouter 首次调用时通过 seed 函数填充，CRUD handler 直接读写。
 */
import type { ProfileResponse, EventResponse } from '@campfire/ts-shared';
import type { CaseResponse } from '@campfire/ts-shared';
import type { NarrativeDetail } from '../../../cases/types';
import type { CardData } from '../../../cases/services/cardApi';
import type { ConsultationHistoryDetail } from '../../../consult/types';

export class MockDatabase {
  private static instance: MockDatabase;

  profiles: ProfileResponse[] = [];
  events: Map<string, EventResponse[]> = new Map();
  cases: CaseResponse[] = [];
  narratives: NarrativeDetail[] = [];
  cards: CardData[] = [];
  consultations: ConsultationHistoryDetail[] = [];

  static getInstance(): MockDatabase {
    if (!MockDatabase.instance) {
      MockDatabase.instance = new MockDatabase();
    }
    return MockDatabase.instance;
  }

  reset(): void {
    this.profiles = [];
    this.events.clear();
    this.cases = [];
    this.narratives = [];
    this.cards = [];
    this.consultations = [];
  }
}
