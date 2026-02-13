import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';

@Entity({ name: 'tg_users' })
export class User {
  @PrimaryGeneratedColumn()
  id!: number;

  @Index({ unique: true })
  @Column({ type: 'bigint', name: 'tg_id' })
  tgId!: string;

  @Column({ type: 'boolean', name: 'is_active', default: true })
  isActive!: boolean;

  @Column({ type: 'varchar', nullable: true })
  username?: string | null;

  @Column({ type: 'varchar', name: 'first_name', nullable: true })
  firstName?: string | null;

  @Column({ type: 'varchar', name: 'last_name', nullable: true })
  lastName?: string | null;

  @Column({ type: 'int', name: 'time_shift', nullable: true })
  timeShift?: number | null;

  @Column({ type: 'varchar', name: 'time_zone', nullable: true })
  timeZone?: string | null;

  @Column({ type: 'varchar', name: 'language_code', nullable: true })
  languageCode?: string | null;

  @Column({ type: 'boolean', name: 'is_chat', default: false })
  isChat!: boolean;

  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt!: Date;

  @UpdateDateColumn({ type: 'timestamptz', name: 'updated_at' })
  updatedAt!: Date;
}
