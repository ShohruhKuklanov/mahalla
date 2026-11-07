-- Car models live in the server catalog (economy.ts CAR.models) so new ones need no schema change.
alter table cars drop constraint if exists cars_model_check;
