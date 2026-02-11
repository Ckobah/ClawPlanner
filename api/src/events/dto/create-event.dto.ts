import { Type } from 'class-transformer';
import { IsArray, IsIn, IsInt, IsOptional, IsString, Matches } from 'class-validator';

const recurrenceValues = ['never', 'daily', 'weekly', 'monthly', 'annual'] as const;

export class CreateEventDto {
  @IsString()
  @Matches(/^\d{4}-\d{2}-\d{2}$/)
  date!: string;

  @IsString()
  @Matches(/^\d{2}:\d{2}$/)
  start_time!: string;

  @IsOptional()
  @IsString()
  @Matches(/^\d{2}:\d{2}$/)
  stop_time?: string;

  @IsString()
  description!: string;

  @IsIn(recurrenceValues)
  recurrent!: (typeof recurrenceValues)[number];

  @IsOptional()
  @IsArray()
  @IsInt({ each: true })
  @Type(() => Number)
  participants?: number[];
}
