export declare class User {
    id: number;
    tgId: string;
    isActive: boolean;
    username?: string | null;
    firstName?: string | null;
    lastName?: string | null;
    timeShift?: number | null;
    timeZone?: string | null;
    languageCode?: string | null;
    isChat: boolean;
    createdAt: Date;
    updatedAt: Date;
}
