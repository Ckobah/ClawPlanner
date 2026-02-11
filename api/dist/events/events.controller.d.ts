import type { Request } from 'express';
import { CreateEventDto } from './dto/create-event.dto';
import { EventsService } from './events.service';
export declare class EventsController {
    private readonly events;
    constructor(events: EventsService);
    getMonth(req: Request, year: string, month: string): Promise<{
        days: Record<number, number>;
    }>;
    getDay(req: Request, year: string, month: string, day: string): Promise<{
        id: number;
        description: string;
        start_time: string;
        stop_time: string | null;
        recurrent: ("daily" | "weekly" | "monthly" | "never" | "annual") | "";
        single_event: boolean;
    }[]>;
    create(req: Request, dto: CreateEventDto): Promise<{
        id: number;
    }>;
    delete(req: Request, id: string, date?: string): Promise<{
        canceled: boolean;
        deleted?: undefined;
    } | {
        deleted: boolean;
        canceled?: undefined;
    }>;
}
