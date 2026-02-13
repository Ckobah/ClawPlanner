import { Column, Entity, PrimaryColumn } from 'typeorm';

@Entity({ name: 'user_relations' })
export class UserRelation {
  @PrimaryColumn({ type: 'int', name: 'user_id' })
  userId!: number;

  @PrimaryColumn({ type: 'int', name: 'related_user_id' })
  relatedUserId!: number;
}
