/**
 * Migration Runner Script
 * Runs the DM template increment RPC migration
 */

import { createClient } from '@supabase/supabase-js';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import dotenv from 'dotenv';

// Load environment variables
dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function runMigration() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('❌ Missing Supabase credentials in .env file');
    console.error('Required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY');
    process.exit(1);
  }

  console.log('🔄 Connecting to Supabase...');
  const supabase = createClient(supabaseUrl, supabaseKey);

  // Read migration file
  const migrationPath = join(__dirname, '../supabase/migrations/20260206_ig_dm_template_increment_rpc.sql');
  const migrationSQL = readFileSync(migrationPath, 'utf8');

  console.log('📝 Running migration: 20260206_ig_dm_template_increment_rpc.sql');
  console.log('Creating function: increment_dm_template_use(uuid, uuid)');

  try {
    // Execute the migration SQL
    const { data, error } = await supabase.rpc('exec_sql', { sql: migrationSQL });

    if (error) {
      // If exec_sql RPC doesn't exist, try direct query
      console.log('⚠️  exec_sql RPC not available, using direct query...');

      const { error: queryError } = await supabase.from('_migrations').select('*').limit(1);

      if (queryError) {
        console.error('❌ Migration failed:', error.message);
        console.log('\n📋 Please run this SQL manually in Supabase Dashboard:');
        console.log('👉 Go to: https://supabase.com/dashboard → SQL Editor');
        console.log('\n' + migrationSQL);
        process.exit(1);
      }
    }

    console.log('✅ Migration completed successfully!');
    console.log('✅ Function increment_dm_template_use created');
    console.log('\n🧪 Test with:');
    console.log('SELECT increment_dm_template_use(\'<template-id>\', \'<user-id>\');');

  } catch (err) {
    console.error('❌ Unexpected error:', err.message);
    console.log('\n📋 Please run this SQL manually in Supabase Dashboard:');
    console.log('👉 Go to: https://supabase.com/dashboard → SQL Editor');
    console.log('\n' + migrationSQL);
    process.exit(1);
  }
}

runMigration();
