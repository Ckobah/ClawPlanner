import { Column, Entity, PrimaryGeneratedColumn } from 'typeorm';

@Entity({ name: 'canceled_events' })
export class CanceledEvent {
  @PrimaryGeneratedColumn()
  id!: number;

  @Column({ type: 'date', name: 'cancel_date' })
  cancelDate!: string;

  @Column({ type: 'int', name: 'event_id' })
  eventId!: number;
}
