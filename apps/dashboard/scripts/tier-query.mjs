import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseKey) {
  console.error('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY');
  console.error('Available env vars:', Object.keys(process.env).filter(k => k.includes('SUPA')));
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function getTierBreakdown() {
  console.log('\n📊 TIER DISTRIBUTION\n' + '='.repeat(50));

  // Get workspace tier distribution
  const { data: workspaces, error: wsError } = await supabase
    .from('workspaces')
    .select('id, owner_id, subscription');

  if (wsError) {
    console.error('Workspaces query failed:', wsError.message);
    return;
  }

  // Count by tier
  const tierCounts = { free: 0, pro: 0, empire: 0 };
  workspaces?.forEach(ws => {
    const tier = ws.subscription?.tier || 'free';
    tierCounts[tier] = (tierCounts[tier] || 0) + 1;
  });

  console.log('\nWorkspaces by Tier:');
  const total = workspaces?.length || 0;
  for (const [tier, count] of Object.entries(tierCounts)) {
    const pct = ((count / Math.max(total, 1)) * 100).toFixed(1);
    const label = tier.toUpperCase().padEnd(8);
    const num = String(count).padStart(5);
    console.log('  ' + label + num + ' (' + pct + '%)');
  }
  console.log('  TOTAL   ' + String(total).padStart(5));

  // Get total accounts
  const { count: accountCount } = await supabase
    .from('accounts')
    .select('*', { count: 'exact', head: true });

  console.log('\nTotal Connected Accounts: ' + (accountCount || 0));

  // Get total posts
  const { count: postCount } = await supabase
    .from('posts')
    .select('*', { count: 'exact', head: true });

  console.log('Total Posts Created: ' + (postCount || 0));

  // Get active users (posted in last 30 days)
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
  const { data: recentPosts } = await supabase
    .from('posts')
    .select('user_id')
    .gte('created_at', thirtyDaysAgo);

  const activeUsers = new Set(recentPosts?.map(p => p.user_id)).size;
  console.log('Active Users (30d): ' + activeUsers);

  // AI config adoption
  const { count: aiConfigCount } = await supabase
    .from('ai_config')
    .select('*', { count: 'exact', head: true });

  console.log('Users with AI Configured: ' + (aiConfigCount || 0));

  // Inspiration configs (Empire feature)
  const { count: inspirationCount } = await supabase
    .from('inspiration_config')
    .select('*', { count: 'exact', head: true });

  console.log('Inspiration Engine Users: ' + (inspirationCount || 0));

  // Auto-post configs
  const { count: autoPostCount } = await supabase
    .from('auto_post_config')
    .select('*', { count: 'exact', head: true });

  console.log('Auto-Poster Users: ' + (autoPostCount || 0));

  // Competitor tracking
  const { count: competitorUsers } = await supabase
    .from('competitors')
    .select('user_id', { count: 'exact', head: true });

  console.log('Users Tracking Competitors: ' + (competitorUsers || 0));

  console.log('\n' + '='.repeat(50));
}

getTierBreakdown().catch(console.error);
