import { Repository } from 'typeorm';
import { ConfigService } from '@nestjs/config';
import { CanceledEvent } from '../entities/canceled-event.entity';
import { Event } from '../entities/event.entity';
import { User } from '../entities/user.entity';
import { CreateEventDto } from './dto/create-event.dto';
type Recurrence = 'never' | 'daily' | 'weekly' | 'monthly' | 'annual';
export declare class EventsService {
    private readonly config;
    private readonly events;
    private readonly users;
    private readonly canceled;
    constructor(config: ConfigService, events: Repository<Event>, users: Repository<User>, canceled: Repository<CanceledEvent>);
    getMonth(userId: number, year: number, month: number): Promise<{
        days: Record<number, number>;
    }>;
    getDay(userId: number, year: number, month: number, day: number): Promise<{
        id: number;
        description: string;
        start_time: string;
        stop_time: string | null;
        recurrent: Recurrence | "";
        single_event: boolean;
    }[]>;
    createEvent(userId: number, dto: CreateEventDto): Promise<{
        id: number;
    }>;
    deleteEvent(userId: number, eventId: number, date?: string): Promise<{
        canceled: boolean;
        deleted?: undefined;
    } | {
        deleted: boolean;
        canceled?: undefined;
    }>;
    private copyToParticipants;
    private getUser;
    private getUserTz;
    private getCanceledMap;
    private isCanceled;
    private initMonthDays;
    private range;
    private weekdayToDb;
}
export {};
