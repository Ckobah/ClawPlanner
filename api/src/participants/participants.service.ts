import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { In, Repository } from 'typeorm';
import { User } from '../entities/user.entity';
import { UserRelation } from '../entities/user-relation.entity';

@Injectable()
export class ParticipantsService {
  constructor(
    @InjectRepository(User) private readonly users: Repository<User>,
    @InjectRepository(UserRelation) private readonly relations: Repository<UserRelation>,
  ) {}

  async listParticipants(ownerTgId: number) {
    const owner = await this.users.findOne({ where: { tgId: String(ownerTgId) } });
    if (!owner) {
      return [];
    }

    const relations = await this.relations.find({ where: { userId: owner.id } });
    const relatedIds = relations.map((rel) => rel.relatedUserId);
    if (!relatedIds.length) {
      return [];
    }

    const relatedUsers = await this.users.find({ where: { id: In(relatedIds) } });
    return relatedUsers.map((user) => ({
      tg_id: Number(user.tgId),
      first_name: user.firstName ?? '',
      is_active: user.isActive,
    }));
  }

  async deleteParticipants(ownerTgId: number, relatedTgIds: number[]) {
    const owner = await this.users.findOne({ where: { tgId: String(ownerTgId) } });
    if (!owner || !relatedTgIds.length) {
      return 0;
    }

    const relatedUsers = await this.users.find({ where: { tgId: In(relatedTgIds.map(String)) } });
    if (!relatedUsers.length) {
      return 0;
    }

    const relatedIds = relatedUsers.map((user) => user.id);
    const result = await this.relations.delete({
      userId: owner.id,
      relatedUserId: In(relatedIds),
    });
    return result.affected ?? 0;
  }
}
