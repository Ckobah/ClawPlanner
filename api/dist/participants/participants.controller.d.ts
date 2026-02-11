import type { Request } from 'express';
import { DeleteParticipantsDto } from './dto/delete-participants.dto';
import { ParticipantsService } from './participants.service';
export declare class ParticipantsController {
    private readonly participants;
    constructor(participants: ParticipantsService);
    list(req: Request): Promise<{
        tg_id: number;
        first_name: string;
        is_active: boolean;
    }[]>;
    delete(req: Request, dto: DeleteParticipantsDto): Promise<{
        removed: number;
    }>;
}
