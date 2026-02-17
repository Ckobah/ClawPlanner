export declare class Event {
    id: number;
    description: string;
    startTime: string;
    startAt: Date;
    stopAt?: Date | null;
    singleEvent?: boolean | null;
    daily?: boolean | null;
    weekly?: number | null;
    monthly?: number | null;
    annualDay?: number | null;
    annualMonth?: number | null;
    tgId: number;
    createdAt: Date;
}
