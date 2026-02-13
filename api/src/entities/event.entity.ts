import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  PrimaryGeneratedColumn,
} from 'typeorm';

@Entity({ name: 'events' })
export class Event {
  @PrimaryGeneratedColumn()
  id!: number;

  @Column({ type: 'varchar' })
  description!: string;

  @Column({ type: 'time', name: 'start_time' })
  startTime!: string;

  @Index()
  @Column({ type: 'timestamptz', name: 'start_at' })
  startAt!: Date;

  @Column({ type: 'timestamptz', name: 'stop_at', nullable: true })
  stopAt?: Date | null;

  @Column({ type: 'boolean', name: 'single_event', nullable: true })
  singleEvent?: boolean | null;

  @Column({ type: 'boolean', nullable: true })
  daily?: boolean | null;

  @Column({ type: 'int', nullable: true })
  weekly?: number | null;

  @Column({ type: 'int', nullable: true })
  monthly?: number | null;

  @Column({ type: 'int', name: 'annual_day', nullable: true })
  annualDay?: number | null;

  @Column({ type: 'int', name: 'annual_month', nullable: true })
  annualMonth?: number | null;

  @Index()
  @Column({ type: 'int', name: 'tg_id' })
  tgId!: number;

  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt!: Date;
}
