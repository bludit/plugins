<?php
// This plugin does not use system() or exec(), those are forbidden.
class pluginBenign extends Plugin {
	public function siteHead() { return '<meta name="x" content="'.Sanitize::html($this->getValue('tag')).'">'; }
}
