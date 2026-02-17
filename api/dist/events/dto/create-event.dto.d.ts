declare const recurrenceValues: readonly ["never", "daily", "weekly", "monthly", "annual"];
export declare class CreateEventDto {
    date: string;
    start_time: string;
    stop_time?: string;
    description: string;
    recurrent: (typeof recurrenceValues)[number];
    participants?: number[];
}
export {};
