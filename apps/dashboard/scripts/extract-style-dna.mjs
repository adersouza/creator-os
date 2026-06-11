/**
 * Manual test script for style DNA extraction
 *
 * Run with: node scripts/extract-style-dna.mjs
 *
 * Requires:
 * - .env with SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
 * - .env with GEMINI_API_KEY or user's ai_config in Supabase
 */

import { createClient } from '@supabase/supabase-js';
import { GoogleGenAI } from '@google/genai';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY;
const geminiApiKey = process.env.GEMINI_API_KEY;

if (!supabaseUrl || !supabaseKey) {
  console.error('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY');
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function getTopPosts(userId, limit = 20) {
  const { data: posts, error } = await supabase
    .from('posts')
    .select('content, likes_count, replies_count, reposts_count, status')
    .eq('user_id', userId)
    .in('status', ['published', 'PUBLISHED'])
    .not('content', 'is', null)
    .order('created_at', { ascending: false });

  if (error) {
    console.error('Error fetching posts:', error.message);
    return [];
  }

  // Filter posts with meaningful content and sort by engagement
  const filtered = posts.filter(p => p.content && p.content.length > 20);

  const sorted = filtered.sort((a, b) => {
    const engA = (a.likes_count || 0) + (a.replies_count || 0) * 2 + (a.reposts_count || 0) * 3;
    const engB = (b.likes_count || 0) + (b.replies_count || 0) * 2 + (b.reposts_count || 0) * 3;
    return engB - engA;
  });

  return sorted.slice(0, limit).map(p => p.content);
}

async function extractStyleDNA(posts, apiKey) {
  if (!posts || posts.length < 5) {
    console.warn('Need at least 5 posts for meaningful extraction');
    return null;
  }

  const postsContext = posts
    .slice(0, 20)
    .map((p, i) => `${i + 1}. ${p}`)
    .join('\n\n');

  const prompt = `Analyze these posts from a single creator and extract their writing DNA.

POSTS:
${postsContext}

Extract and return a JSON object with:

{
  "sentence_patterns": {
    "avg_length": "short" | "medium" | "long",
    "structure": "simple" | "compound" | "fragmented" | "mixed",
    "rhythm": "description of their writing cadence"
  },
  "hooks": {
    "patterns": ["list 3-5 opening patterns they use"],
    "examples": ["direct quotes of their best hooks - max 15 words each"]
  },
  "closings": {
    "patterns": ["how they typically end posts"],
    "cta_style": "none" | "soft" | "direct" | "link-focused"
  },
  "emoji_usage": {
    "frequency": "none" | "rare" | "moderate" | "heavy",
    "placement": "start" | "end" | "inline" | "emphasis",
    "favorites": ["most used emojis - list up to 5"]
  },
  "vocabulary": {
    "signature_words": ["words or phrases they overuse intentionally - max 10"],
    "avoid_words": ["words they seem to never use - max 5"],
    "tone_markers": ["phrases that define their unique voice - max 5"]
  },
  "tone": {
    "vibe": "describe their overall vibe in 3-5 words",
    "energy": "low-key" | "moderate" | "high-energy" | "chaotic"
  },
  "length": {
    "typical_chars": "estimate typical character count range (e.g., '80-180')",
    "preference": "very-short" | "short" | "medium" | "long"
  },
  "punctuation": {
    "quirks": ["specific punctuation habits like 'lots of !', 'minimal commas'"],
    "question_frequency": "never" | "rare" | "often" | "signature"
  },
  "closings": {
    "patterns": ["how they typically end posts"],
    "cta_style": "none" | "soft" | "direct" | "link-focused"
  },
  "formatting": {
    "line_breaks": "minimal" | "moderate" | "heavy",
    "lists": true | false,
    "caps_usage": "none" | "emphasis" | "shouting"
  }
}

CRITICAL: Be extremely specific. Quote actual examples. This will be used to generate content that sounds EXACTLY like this person wrote it.

Return ONLY valid JSON, no markdown.`;

  try {
    const client = new GoogleGenAI({ apiKey });

    console.log('\nCalling Gemini API...');
    const result = await client.models.generateContent({
      model: 'gemini-2.0-flash',
      contents: prompt,
    });
    const response = result.text || '';

    // Parse JSON response
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      console.error('No JSON found in response');
      console.log('Raw response:', response);
      return null;
    }

    const extracted = JSON.parse(jsonMatch[0]);
    extracted.extracted_at = new Date().toISOString();

    return extracted;
  } catch (error) {
    console.error('Extraction failed:', error.message);
    return null;
  }
}

async function saveToAccount(accountId, styleDNA) {
  // Get existing ai_config
  const { data: account } = await supabase
    .from('accounts')
    .select('ai_config')
    .eq('id', accountId)
    .single();

  const existingConfig = account?.ai_config || {};
  const updatedConfig = {
    ...existingConfig,
    extracted_style: styleDNA,
  };

  const { error } = await supabase
    .from('accounts')
    .update({ ai_config: updatedConfig })
    .eq('id', accountId);

  return !error;
}

async function main() {
  console.log('\n🧬 STYLE DNA EXTRACTION\n' + '='.repeat(60));

  // Get API key - first try env, then try user's ai_config
  let apiKey = geminiApiKey;

  if (!apiKey) {
    console.log('No GEMINI_API_KEY in env, checking user ai_config...');

    // Get the first user's AI config
    const { data: configs } = await supabase
      .from('ai_config')
      .select('api_key, provider')
      .eq('provider', 'gemini')
      .limit(1);

    if (configs && configs.length > 0 && configs[0].api_key) {
      apiKey = configs[0].api_key;
      console.log('Found Gemini API key in user config');
    }
  }

  if (!apiKey) {
    console.error('\nNo API key available. Set GEMINI_API_KEY in .env or configure in app.');
    process.exit(1);
  }

  // Get first user with posts
  const { data: workspaces } = await supabase
    .from('workspaces')
    .select('owner_id')
    .limit(1);

  if (!workspaces || workspaces.length === 0) {
    console.error('No workspaces found');
    process.exit(1);
  }

  const userId = workspaces[0].owner_id;
  console.log('User ID:', userId.substring(0, 8) + '...');

  // Get first account for this user
  const { data: accounts } = await supabase
    .from('accounts')
    .select('id, username')
    .eq('user_id', userId)
    .limit(1);

  if (!accounts || accounts.length === 0) {
    console.error('No accounts found');
    process.exit(1);
  }

  const account = accounts[0];
  console.log('Account:', '@' + account.username);

  // Get top posts
  console.log('\nFetching top posts...');
  const posts = await getTopPosts(userId);
  console.log(`Found ${posts.length} published posts`);

  if (posts.length < 5) {
    console.error('Need at least 5 posts for extraction');
    process.exit(1);
  }

  // Show first few posts
  console.log('\nSample posts:');
  posts.slice(0, 3).forEach((p, i) => {
    const preview = p.length > 100 ? p.substring(0, 100) + '...' : p;
    console.log(`  ${i + 1}. ${preview}`);
  });

  // Extract style DNA
  console.log('\n' + '='.repeat(60));
  console.log('Extracting style DNA from', posts.length, 'posts...');

  const styleDNA = await extractStyleDNA(posts, apiKey);

  if (styleDNA) {
    console.log('\n✅ EXTRACTION SUCCESSFUL\n');
    console.log(JSON.stringify(styleDNA, null, 2));

    // Save to account
    console.log('\n' + '='.repeat(60));
    console.log('💾 Saving to account @' + account.username + '...');
    const saved = await saveToAccount(account.id, styleDNA);

    if (saved) {
      console.log('✅ Saved to accounts.ai_config.extracted_style');
    } else {
      console.log('❌ Failed to save');
    }

    // Summary
    console.log('\n' + '='.repeat(60));
    console.log('📊 SUMMARY:');
    console.log('  Vibe:', styleDNA.tone?.vibe || 'N/A');
    console.log('  Energy:', styleDNA.tone?.energy || 'N/A');
    console.log('  Length:', styleDNA.length?.typical_chars || 'N/A', `(${styleDNA.length?.preference || 'N/A'})`);
    console.log('  Hook patterns:', styleDNA.hooks?.patterns?.length || 0);
    console.log('  Signature words:', styleDNA.vocabulary?.signature_words?.slice(0, 5).join(', '));
    console.log('  Emoji usage:', styleDNA.emoji_usage?.frequency);
    console.log('  Punctuation:', styleDNA.punctuation?.quirks?.join(', ') || 'N/A');

    // Show what the prompt injection looks like
    console.log('\n' + '='.repeat(60));
    console.log('📝 PROMPT INJECTION PREVIEW:');
    console.log('(This is what gets added to AI post generation prompts)\n');

    const promptParts = [];
    if (styleDNA.hooks?.patterns?.length > 0) {
      promptParts.push(`🎯 HOOK PATTERNS: ${styleDNA.hooks.patterns.join(' | ')}`);
    }
    if (styleDNA.vocabulary?.signature_words?.length > 0) {
      promptParts.push(`🗣️ SIGNATURE PHRASES: ${styleDNA.vocabulary.signature_words.join(', ')}`);
    }
    if (styleDNA.tone?.vibe) {
      promptParts.push(`🎭 VIBE: ${styleDNA.tone.vibe} (${styleDNA.tone.energy} energy)`);
    }
    if (styleDNA.length?.typical_chars) {
      promptParts.push(`📏 LENGTH: ${styleDNA.length.typical_chars} chars (${styleDNA.length.preference})`);
    }
    if (styleDNA.emoji_usage?.favorites?.length > 0) {
      promptParts.push(`😊 EMOJIS: ${styleDNA.emoji_usage.frequency}, at ${styleDNA.emoji_usage.placement}, prefer: ${styleDNA.emoji_usage.favorites.join(' ')}`);
    }
    if (styleDNA.punctuation?.quirks?.length > 0) {
      promptParts.push(`❗ PUNCTUATION: ${styleDNA.punctuation.quirks.join(', ')}`);
    }

    console.log(promptParts.join('\n'));

    console.log('\n⛔ VIOLATIONS (do NOT add):');
    console.log('- Motivational quotes, corporate jargon, long explanations');
    console.log('- Questions unless in hook patterns above');
    console.log('- Generic phrases like "Let me know what you think"');
  } else {
    console.log('\n❌ Extraction failed');
  }

  console.log('\n' + '='.repeat(60));
}

main().catch(console.error);
